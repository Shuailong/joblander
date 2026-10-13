"""GCP 形态：计量服务按 X-Joblander-Tenant 认账户（调用方由 Cloud Run IAM 限定为引擎 / 任务服务）；
共享引擎后端的令牌格式与引擎一致；PgLeader 同一时刻只让一个实例领头。"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from gw.meter import create_meter_app
from gw.shared import tenant_token
from gw.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "gw.sqlite"))
    s.create("a@x.com", 1.0)
    s.set_status("a@x.com", "ready", machine_id="shared", volume_id="tenant-aaaaaa")
    return s


def test_meter_identifies_account_by_tenant_header(store):
    c = TestClient(create_meter_app(store, "sk", {"m": {"input": 1, "output": 1}}, trust_tenant_header=True))
    assert c.get("/healthz").json() == {"ok": True}
    ok = c.post("/v1/events", json={"events": [{"name": "GET /sourcing", "at": time.time()}]},
                headers={"x-joblander-tenant": "tenant-aaaaaa"})
    assert ok.json() == {"ok": True, "n": 1}
    assert c.post("/v1/events", json={"events": []}).status_code == 401                    # 没指明账户
    assert c.post("/v1/events", json={"events": []},
                  headers={"x-joblander-tenant": "tenant-zzzzzz"}).status_code == 401       # 不存在的账户
    # Fly 形态的子 key 在 GCP 计量服务上不认
    assert c.post("/v1/events", json={"events": []},
                  headers={"authorization": "Bearer whatever"}).status_code == 401


def test_tenant_token_matches_engine_format():
    import importlib.util
    if importlib.util.find_spec("joblander") is None:
        pytest.skip("引擎包未安装")
    from joblander.cloud import tokens
    tok = tenant_token("tenant-aaaaaa", "k" * 40, now=1000)
    assert tokens.verify(tok, key=b"k" * 40, now=1100) == "tenant-aaaaaa"


# ---------- 隐私 v2：行为数据开关、会话事件、清理 ----------

import httpx  # noqa: E402

from gw import pages, privacy_v2  # noqa: E402
from gw.events import SessionEvents, Sweeper, user_key  # noqa: E402
from gw.web import Settings, create_web_app, make_session  # noqa: E402


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.setattr(pages, "PRIVACY_VERSION", privacy_v2.VERSION)
    monkeypatch.setattr(pages, "_PRIV", privacy_v2.PRIV)
    monkeypatch.setattr(pages, "_CONSENT", privacy_v2.CONSENT)
    monkeypatch.setenv("JOBLANDER_LOG_SALT", "salt")
    monkeypatch.setenv("GW_MODE", "gcp")                       # 来源 IP 按负载均衡器的 X-Forwarded-For 取


class FakePublisher:
    def __init__(self):
        self.events = []

    def emit(self, e):
        self.events.append(e)


def _web(store, seen, events=None):
    s = Settings(public_host="app.test", session_secret="s", google_client_id="c", google_client_secret="x",
                 user_image="", meter_url="http://m/v1")
    s.events = events

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(200, html="<h1>ok</h1>")
    from gw.flyapi import Fly
    fly = Fly("tok", "users", "sin", httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))))
    return TestClient(create_web_app(s, store, fly, httpx.AsyncClient(transport=httpx.MockTransport(handler))),
                      base_url="https://app.test")


def _new_user(store, email="n@x.com"):
    store.create(email, 1.0)
    store.db.execute("UPDATE users SET created_at=? WHERE email=?", (privacy_v2.effective_ts() + 60, email))
    store.set_status(email, "ready", machine_id="m_1", volume_id="tenant-nnnnnn")


def test_analytics_rules(store, v2):
    store.consent("a@x.com", privacy_v2.VERSION)                  # 已有用户（开通早于 v2 生效）
    u = store.get("a@x.com")
    assert not privacy_v2.analytics_allowed(u, now=u.consented_at + 3600)          # 退出期内不采集
    assert privacy_v2.analytics_allowed(u, now=u.consented_at + 15 * 86400)
    assert privacy_v2.analytics_starts(u) == u.consented_at + 14 * 86400
    _new_user(store)
    store.consent("n@x.com", privacy_v2.VERSION)
    assert privacy_v2.analytics_allowed(store.get("n@x.com"))                       # 新用户：确认即可
    store.set_analytics("n@x.com", False)
    assert not privacy_v2.analytics_allowed(store.get("n@x.com"))
    store.consent("a@x.com", "2026-10-05")                         # 还停在 v1 的同意
    assert not privacy_v2.analytics_allowed(store.get("a@x.com"), now=time.time() + 30 * 86400)


def test_consent_page_and_settings_switch(store, v2):
    _new_user(store)
    c = _web(store, [])
    c.cookies.set("jl_session", make_session("s", "n@x.com"))
    page = c.get("/").text
    assert 'name="analytics"' in page and "帮助改进产品" in page                     # 确认页上有开关，默认勾着
    r = c.post("/_gw/consent", data={}, headers={"origin": "https://app.test"}, follow_redirects=False)
    assert r.status_code == 303 and store.get("n@x.com").analytics_off               # 没勾 = 关
    c.post("/_gw/consent", data={"analytics": "1"}, headers={"origin": "https://app.test"}, follow_redirects=False)
    assert store.get("n@x.com").analytics_off is None
    me = c.get("/_gw/me").json()
    assert me["analytics"]["on"] and me["analytics"]["active"]
    out = c.post("/_gw/analytics", data={"on": "0"}, headers={"origin": "https://app.test"}).json()
    assert out["analytics"] == {"on": False, "active": False, "starts": None}
    assert c.post("/_gw/analytics", data={"on": "1"}, headers={"origin": "https://evil.test"}).status_code == 403


def test_proxy_passes_analytics_flag_and_emits_one_session_event_a_day(store, v2):
    _new_user(store)
    store.consent("n@x.com", privacy_v2.VERSION)
    seen, pub = [], FakePublisher()
    c = _web(store, seen, SessionEvents(pub))
    c.cookies.set("jl_session", make_session("s", "n@x.com"))
    hdr = {"x-forwarded-for": "6.6.6.6, 203.0.113.7, 130.211.0.1",        # 第一段是客户端自己写的，不能信
           "fly-client-ip": "6.6.6.6", "x-client-geo-location": "SG,SG01,Singapore",
           "user-agent": "Mozilla/5.0 (iPhone) Mobile Safari/604.1"}
    c.get("/", headers=hdr)
    c.get("/sourcing", headers=hdr)
    assert seen[-1].headers["x-joblander-analytics"] == "on"
    assert len(pub.events) == 1
    ev = pub.events[0]
    assert ev["user_key"] == user_key("tenant-nnnnnn") and ev["ip"] == "203.0.113.7"
    assert (ev["country"], ev["city"], ev["device"], ev["browser"]) == ("SG", "Singapore", "mobile", "safari")
    assert "email" not in json.dumps(ev) and "n@x.com" not in json.dumps(ev)
    store.set_analytics("n@x.com", False)
    c.get("/", headers={**hdr, "x-joblander-analytics": "on"})                       # 浏览器自己带 on 也没用
    assert seen[-1].headers["x-joblander-analytics"] == "off" and len(pub.events) == 1


def _bq(sent, complete=True):
    def handler(req: httpx.Request):
        sent.append(json.loads(req.content))
        return httpx.Response(200, json={"jobComplete": complete})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _sweeper(store, client, table="proj.jl_prod_raw.product_events"):
    sw = Sweeper(store, table, client=client)

    async def token():
        return "tok"
    sw.pub._access_token = token
    return sw


def test_sweeper_purges_once_per_switch_off_and_truncates_ips(store, v2):
    import asyncio
    _new_user(store)
    store.set_analytics("n@x.com", False)
    sent = []
    sw = _sweeper(store, _bq(sent))
    later = time.time() + 3601
    assert asyncio.run(sw.sweep()) == 0 and len(sent) == 1                     # 刚关：等路上的事件落地再清
    sent.clear()
    assert asyncio.run(sw.sweep(now=later)) == 1
    purge, trunc = sent
    assert purge["queryParameters"][0]["parameterValue"]["value"] == user_key("tenant-nnnnnn")
    assert "DELETE FROM `proj.jl_prod_raw.product_events`" in purge["query"]
    assert "JSON_REMOVE(data, '$.ip')" in trunc["query"] and "INTERVAL 90 DAY" in trunc["query"]
    assert not any("n@x.com" in k for k, _ in store.kv_items("analytics_"))   # 标记里不放邮箱
    sent.clear()
    assert asyncio.run(sw.sweep(now=later)) == 0 and len(sent) == 1            # 同一次关闭只清一回
    store.set_analytics("n@x.com", True)
    store.set_analytics("n@x.com", False)                                      # 又关了一次：再清
    assert asyncio.run(sw.sweep(now=later + 10)) == 1


def test_sweeper_retries_when_bigquery_did_not_finish(store, v2):
    import asyncio
    _new_user(store)
    store.set_analytics("n@x.com", False)
    sent = []
    later = time.time() + 3601
    assert asyncio.run(_sweeper(store, _bq(sent, complete=False)).sweep(now=later)) == 0
    assert asyncio.run(_sweeper(store, _bq(sent)).sweep(now=later)) == 1


def test_deleted_account_behavior_data_is_queued_and_purged(store, v2):
    import asyncio

    from gw.events import forget
    _new_user(store)
    forget(store, "tenant-nnnnnn")
    store.delete_user("n@x.com")
    sent = []
    assert asyncio.run(_sweeper(store, _bq(sent)).sweep(now=time.time() + 3601)) == 1
    assert sent[0]["queryParameters"][0]["parameterValue"]["value"] == user_key("tenant-nnnnnn")
    assert store.kv_items("analytics_purge:") == []


def test_full_ips_are_truncated_after_90_days(store, v2):
    import asyncio
    store.set_geo("old@x.com", "203.0.113.9", {"country": "SG", "city": "Singapore"})
    store.set_geo("new@x.com", "198.51.100.4", {"country": "MY", "city": "Kuala Lumpur"})
    store.db.execute("UPDATE geo SET at=? WHERE email=?", (time.time() - 91 * 86400, "old@x.com"))
    asyncio.run(Sweeper(store, None).sweep())                                  # 没配 BigQuery 也截网关库里的
    rows = {r["email"]: (r["ip"], r["city"]) for r in store.db.execute("SELECT email, ip, city FROM geo")}
    assert rows == {"old@x.com": ("", "Singapore"), "new@x.com": ("198.51.100.4", "Kuala Lumpur")}


def test_client_ip_behind_google_load_balancer(monkeypatch):
    from types import SimpleNamespace

    from gw.geo import client_ip
    req = SimpleNamespace(headers={"x-forwarded-for": "6.6.6.6, 203.0.113.7, 130.211.0.1", "fly-client-ip": "6.6.6.6"},
                          client=SimpleNamespace(host="169.254.1.1"))
    monkeypatch.setenv("GW_MODE", "gcp")
    assert client_ip(req) == "203.0.113.7"
    monkeypatch.delenv("GW_MODE")
    assert client_ip(req) == "6.6.6.6"                                         # Fly：入口代理覆盖过这个头


# ---------- 切流：Fly 网关的 SQLite 库 → GCP 网关库 ----------

def _sqlite_store(path):
    """真 SQLite 文件上的网关库（Postgres 模式下 db.connect 换成了连 Postgres，这里绕开）。"""
    import sqlite3

    from gw import db
    from gw.store import Store

    def real(target):
        conn = sqlite3.connect(target, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn
    orig, db.connect = db.connect, real
    try:
        return Store(str(path))
    finally:
        db.connect = orig


def _fly_db(tmp_path):
    from gw.store import MAINTENANCE_KEY
    src = _sqlite_store(tmp_path / "fly.sqlite")
    src.create("a@x.com", 2.0)
    src.set_status("a@x.com", "ready", machine_id="m_1", volume_id="vol_1")
    src.create("n@x.com", 2.0)                                       # 登录过但从没开通
    src.charge("a@x.com", "gpt-5.6-sol", 100, 20, 0.25)
    src.grant("a@x.com", 5, "朋友内测")
    src.enqueue_mail("b@x.com", "invited", "zh", {"x": "1"})
    src.set_kv(MAINTENANCE_KEY, json.dumps({"since": 1.0, "note": "搬家"}))
    src.set_geo("a@x.com", "203.0.113.9", {"country": "SG", "city": "Singapore"})
    return tmp_path / "fly.sqlite"


def _target(tmp_path):
    import os
    return os.environ.get("GW_TEST_PG_DSN") or str(tmp_path / "gcp.sqlite")


PLAN = {"users": [{"email": "a@x.com", "machine_id": "m_1", "volume_id": "vol_1", "tenant_id": "t0123456789abcdef0123"},
                  {"email": "n@x.com", "machine_id": None, "volume_id": None, "tenant_id": None}]}
REPORT = {"tenants": {"t0123456789abcdef0123": {"ok": True}}}


def test_cutover_copies_every_table_and_maps_accounts(tmp_path):
    from gw import cutover
    from gw.store import MAINTENANCE_KEY, Store
    import sqlite3
    src = _fly_db(tmp_path)
    counts = cutover.copy(src, _target(tmp_path), PLAN, REPORT)
    with sqlite3.connect(src) as c:
        assert counts == {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in counts}
    assert counts["users"] == 2 and counts["usage"] == 1 and counts["mail_queue"] == 1 and counts["geo"] == 1
    gcp = Store(_target(tmp_path))
    a, n = gcp.get("a@x.com"), gcp.get("n@x.com")
    assert (a.volume_id, a.machine_id, a.status) == ("t0123456789abcdef0123", "shared", "ready")
    assert (n.volume_id, n.machine_id, n.status) == (None, None, "new")
    assert round(a.balance_usd, 2) == round(2 + 5 - 0.25, 2)                  # 额度与花费原样
    assert gcp.by_tenant("t0123456789abcdef0123").email == "a@x.com"         # 计量按账户号认人
    assert json.loads(gcp.get_kv(MAINTENANCE_KEY))["note"] == "搬家"          # 新网关起来时仍在维护中
    assert gcp.next_mail()["to_email"] == "b@x.com"                            # 没发完的信接着发
    gcp.grant("a@x.com", 1, "切流后")                                          # 自增序列接上了
    assert len([r for r in gcp.db.execute("SELECT id FROM grants")]) == counts["grants"] + 1


def test_cutover_refuses_red_report_and_newer_target(tmp_path):
    import time

    from gw import cutover
    from gw.store import Store
    src = _fly_db(tmp_path)
    with pytest.raises(SystemExit, match="a@x.com"):
        cutover.copy(src, _target(tmp_path), PLAN, {"tenants": {"t0123456789abcdef0123": {"ok": False, "error": "缺 3 个文件"}}})
    cutover.copy(src, _target(tmp_path), PLAN, REPORT)
    cutover.copy(src, _target(tmp_path), PLAN, REPORT)                          # 彩排后再跑：同一份备份可以重来
    Store(_target(tmp_path)).charge("a@x.com", "gpt-5.6-sol", 1, 1, 0.01)     # GCP 已经在服务用户
    Store(_target(tmp_path)).db.execute("UPDATE usage SET at=? WHERE cost_usd=0.01", (time.time() + 3600,))
    with pytest.raises(SystemExit, match="--force"):
        cutover.copy(src, _target(tmp_path), PLAN, REPORT)
    cutover.copy(src, _target(tmp_path), PLAN, REPORT, force=True)
    assert Store(_target(tmp_path)).db.execute("SELECT COUNT(*) AS n FROM usage").fetchone()["n"] == 1


def test_site_pageview_beacon_records_no_ip(store, v2):
    pub = FakePublisher()
    c = _web(store, [], SessionEvents(pub))
    hdr = {"x-forwarded-for": "203.0.113.7, 130.211.0.1", "x-client-geo-location": "SG,SG01,Singapore",
           "user-agent": "Mozilla/5.0 (Macintosh) AppleWebKit Chrome/131 Safari/537.36", "content-type": "text/plain"}
    body = json.dumps({"p": "/interested/", "r": "https://news.ycombinator.com/item?id=123"})
    assert c.post("/_pv", content=body, headers=hdr).status_code == 204
    assert c.post("/_pv", content=json.dumps({"p": "/<script>"}), headers=hdr).status_code == 204   # 怪路径不记
    assert c.post("/_pv", content=b"not json", headers=hdr).status_code == 204
    c.post("/_pv", content=json.dumps({"p": "/"}), headers={**hdr, "user-agent": "Googlebot/2.1"})
    (ev, bot) = pub.events
    assert {k: ev[k] for k in ("type", "path", "ref", "country", "device", "browser")} == \
        {"type": "site_pv", "path": "/interested/", "ref": "news.ycombinator.com", "country": "SG",
         "device": "desktop", "browser": "chrome"}
    assert "ip" not in ev and "user_key" not in ev and bot["device"] == "bot"
