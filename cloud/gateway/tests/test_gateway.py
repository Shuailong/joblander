"""网关回归：钱（计量/额度）、隔离（口令/会话）、开通流程。外部依赖（OpenAI、Fly、Google）全部 mock。"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from gw.flyapi import Fly
from gw.meter import create_meter_app
from gw.store import Store
from gw.web import Settings, create_web_app, make_session, read_session

PRICES = {"m-pro": {"input": 2.0, "output": 8.0}}


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "gw.sqlite"))


# ---------- 计量 ----------

def _openai(captured: list):
    def handler(req: httpx.Request):
        body = json.loads(req.content)
        captured.append({"auth": req.headers["authorization"], "body": body})
        if body.get("stream"):
            sse = (b'data: {"choices":[{"delta":{"content":"hi"}}],"usage":null}\n\n'
                   b'data: {"choices":[],"usage":{"prompt_tokens":1000000,"completion_tokens":500000}}\n\n'
                   b"data: [DONE]\n\n")
            return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 10}})
    return handler


def test_meter_charges_stream_usage_and_hides_real_key(store):
    user, key = store.create("a@x.com", 10.0)
    seen: list = []
    client = TestClient(create_meter_app(store, "sk-REAL", PRICES,
                                         httpx.AsyncClient(transport=httpx.MockTransport(_openai(seen)))))
    r = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                    json={"model": "m-pro", "stream": True, "messages": []})
    assert r.status_code == 200 and '"content":"hi"' in r.text
    assert seen[0]["auth"] == "Bearer sk-REAL"                     # 真 key 只在网关
    assert seen[0]["body"]["stream_options"] == {"include_usage": True}
    # 1M 输入 × $2 + 0.5M 输出 × $8 = $6
    assert store.get("a@x.com").spent_usd == pytest.approx(6.0)


def test_meter_refuses_when_balance_exhausted(store):
    _, key = store.create("a@x.com", 1.0)
    store.charge("a@x.com", "m-pro", 0, 0, 1.0)
    seen: list = []
    client = TestClient(create_meter_app(store, "sk", PRICES,
                                         httpx.AsyncClient(transport=httpx.MockTransport(_openai(seen)))))
    r = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                    json={"model": "m-pro", "stream": True})
    assert r.status_code == 400 and seen == []                     # 拒在花钱之前
    # 引擎侧 _is_budget_error 认这段正文 → 「额度已用完」
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
    from joblander.llm import LLMError, _is_budget_error
    assert _is_budget_error(LLMError(f"400: {r.text}"))


def test_meter_rejects_unknown_key_and_unpriced_model(store):
    _, key = store.create("a@x.com", 5.0)
    client = TestClient(create_meter_app(store, "sk", PRICES,
                                         httpx.AsyncClient(transport=httpx.MockTransport(_openai([])))))
    assert client.post("/v1/chat/completions", headers={"Authorization": "Bearer nope"},
                       json={"model": "m-pro"}).status_code == 401
    assert client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                       json={"model": "gpt-expensive"}).status_code == 400


def test_meter_non_stream_charges(store):
    _, key = store.create("a@x.com", 5.0)
    client = TestClient(create_meter_app(store, "sk", PRICES,
                                         httpx.AsyncClient(transport=httpx.MockTransport(_openai([])))))
    r = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                    json={"model": "m-pro"})
    assert r.status_code == 200
    assert store.get("a@x.com").spent_usd == pytest.approx((100 * 2 + 10 * 8) / 1e6)


# ---------- 会话 ----------

def test_session_roundtrip_tamper_and_expiry():
    c = make_session("k", "a@x.com", now=1000)
    assert read_session("k", c, now=2000) == "a@x.com"
    assert read_session("other", c, now=2000) is None
    import base64
    forged = base64.urlsafe_b64encode(
        base64.urlsafe_b64decode(c).replace(b"a@x.com", b"b@x.com")).decode()
    assert read_session("k", forged, now=2000) is None
    assert read_session("k", c, now=1000 + 31 * 86400) is None


# ---------- 开通 + 转发 ----------

SETTINGS = Settings(public_host="app.test", session_secret="s", google_client_id="cid",
                    google_client_secret="cs", user_image="img:v1",
                    meter_url="http://gw.internal:8081/v1", admins={"boss@x.com"})


def _fly(calls: list):
    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        if req.url.path.endswith("/volumes"):
            return httpx.Response(200, json={"id": "vol_1"})
        if req.url.path.endswith("/machines"):
            return httpx.Response(200, json={"id": "m_1"})
        return httpx.Response(200, json={})
    return Fly("tok", "users", "sin", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _upstream(seen: list):
    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(200, html="<h1>指挥中心</h1>", headers={"set-cookie": "x=1"})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _client(store, fly, upstream, email=None, consent=True):
    c = TestClient(create_web_app(SETTINGS, store, fly, upstream), base_url="https://app.test")
    if email:
        c.cookies.set("jl_session", make_session("s", email))
        if consent and store.get(email):
            from gw.pages import PRIVACY_VERSION
            store.consent(email, PRIVACY_VERSION)
    return c


def test_anonymous_sees_login_and_api_gets_401(store):
    c = _client(store, _fly([]), _upstream([]))
    assert "用 Google 登录" in c.get("/").text
    assert c.get("/_gw/static/shots/command-center-zh-light.webp").status_code == 200
    assert c.post("/api/drill/run").status_code == 401


def test_first_visit_provisions_then_proxies_with_token(store):
    store.create("a@x.com", 2.0)
    calls, seen = [], []
    c = _client(store, _fly(calls), _upstream(seen), "a@x.com")
    r = c.get("/")
    assert "准备独立空间" in r.text and "/_gw/status" in r.text
    import time
    for _ in range(50):
        if store.get("a@x.com").status == "ready":
            break
        time.sleep(0.02)
    u = store.get("a@x.com")
    assert u.status == "ready" and u.machine_id == "m_1" and u.volume_id == "vol_1"
    assert c.get("/_gw/status").json() == {"status": "ready", "stage": 3}
    machine = next(b for m, p, b in calls if p.endswith("/machines"))
    env = machine["config"]["env"]
    assert env["JOBLANDER_GATEWAY_TOKEN"] == u.gateway_token
    assert env["OPENAI_BASE_URL"] == "http://gw.internal:8081/v1"
    assert store.by_meter_key(env["OPENAI_API_KEY"]).email == "a@x.com"   # 子 key 可用
    assert "services" not in machine["config"]                            # 公网不可达

    r = c.get("/pipeline?x=1")
    assert "指挥中心" in r.text
    req = seen[-1]
    assert str(req.url) == "http://m_1.vm.users.internal:8899/pipeline?x=1"
    assert req.headers["x-joblander-gateway"] == u.gateway_token
    assert req.headers["host"] == "app.test"
    assert "cookie" not in req.headers                    # 网关登录态不外泄给 machine
    c.cookies.set("jl_lang", "en")
    c.get("/", headers={"Accept-Language": "zh-CN"})
    assert seen[-1].headers["accept-language"] == "en"   # 首页选的语言带进引擎


def test_client_cannot_forge_gateway_header(store):
    store.create("a@x.com", 2.0)
    store.set_status("a@x.com", "ready", machine_id="m_1")
    seen = []
    c = _client(store, _fly([]), _upstream(seen), "a@x.com")
    c.get("/", headers={"X-Joblander-Gateway": "forged"})
    assert seen[-1].headers["x-joblander-gateway"] == store.get("a@x.com").gateway_token


def test_uninvited_login_is_refused(store, monkeypatch):
    def google(req: httpx.Request):
        if "token" in req.url.path:
            return httpx.Response(200, json={"access_token": "at"})
        return httpx.Response(200, json={"email": "stranger@x.com", "email_verified": True})
    import gw.web as W
    orig = httpx.AsyncClient
    monkeypatch.setattr(W.httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=httpx.MockTransport(google)))
    c = _client(store, _fly([]), _upstream([]))
    c.cookies.set("jl_state", "st")
    r = c.get("/auth/callback?code=c&state=st", follow_redirects=False)
    assert "邀请名单" in r.text and store.get("stranger@x.com") is None
    store.invite("stranger@x.com")
    r = c.get("/auth/callback?code=c&state=st", follow_redirects=False)
    assert r.status_code == 302 and store.get("stranger@x.com").credit_usd == 2.0


def test_blocked_login_notifies_admin_once_and_invite_clears_it(store, monkeypatch):
    mails = []
    def google(req: httpx.Request):
        if "resend" in req.url.host:
            mails.append(json.loads(req.content))
            return httpx.Response(200, json={"id": "e1"})
        if "token" in req.url.path:
            return httpx.Response(200, json={"access_token": "at"})
        return httpx.Response(200, json={"email": "Friend@x.com", "email_verified": True})
    import gw.web as W
    orig = httpx.AsyncClient
    monkeypatch.setattr(W.httpx, "AsyncClient",
                        lambda *a, **k: orig(transport=httpx.MockTransport(google)))
    s = Settings(**{**SETTINGS.__dict__, "feedback_to": "boss@x.com", "resend_api_key": "re_x"})
    c = TestClient(create_web_app(s, store, _fly([]), _upstream([])), base_url="https://app.test")
    for _ in range(3):
        c.cookies.set("jl_state", "st")
        assert "已经收到通知" in c.get("/auth/callback?code=c&state=st", follow_redirects=False).text
    assert len(mails) == 1                                       # 只在第一次被拦时发
    assert mails[0]["to"] == ["boss@x.com"] and mails[0]["reply_to"] == "friend@x.com"
    assert "gw.cli invite friend@x.com" in mails[0]["html"]
    assert [(w["email"], w["attempts"]) for w in store.waitlist()] == [("friend@x.com", 3)]
    store.invite("friend@x.com")
    assert store.waitlist() == []
    assert store.uninvite("friend@x.com") and not store.is_invited("friend@x.com")


def test_bad_state_is_refused(store):
    c = _client(store, _fly([]), _upstream([]))
    c.cookies.set("jl_state", "a")
    assert "登录失败" in c.get("/auth/callback?code=c&state=b").text


def test_balance_endpoint(store):
    store.create("a@x.com", 2.0)
    store.charge("a@x.com", "m-pro", 0, 0, 0.5)
    c = _client(store, _fly([]), _upstream([]), "a@x.com")
    assert c.get("/_gw/balance").json() == {"balance_usd": 1.5, "credit_usd": 2.0, "spent_usd": 0.5}
    assert _client(store, _fly([]), _upstream([])).get("/_gw/balance").status_code == 401


def test_me_endpoint_and_usage_page(store):
    store.create("a@x.com", 2.0)
    store.charge("a@x.com", "m-pro", 0, 0, 0.5)
    store.charge("a@x.com", "m-flash", 0, 0, 1.25)
    c = _client(store, _fly([]), _upstream([]), "a@x.com")
    assert c.get("/_gw/me").json() == {"email": "a@x.com", "admin": False, "balance_usd": 0.25,
                                       "credit_usd": 2.0, "spent_usd": 1.75, "low": True}
    assert _client(store, _fly([]), _upstream([])).get("/_gw/me").status_code == 401
    page = c.get("/_gw/account").text
    assert "用量明细" in page and "$0.25" in page and "/settings#account" in page
    assert "2次" in page and "$1.75" in page                                  # 同一天两次调用并成一行
    assert "/auth/logout" not in page and "m-pro" not in page                 # 退出在设置页；明细不列模型
    en = _client(store, _fly([]), _upstream([]), "a@x.com")
    en.cookies.set("jl_lang", "en")
    assert "Back to settings" in en.get("/_gw/account").text


def test_search_charges_per_call_and_respects_budget(store):
    _, key = store.create("a@x.com", 0.015)
    seen = []

    def tavily(req: httpx.Request):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"results": [{"title": "T", "url": "U", "content": "C"}]})
    client = TestClient(create_meter_app(store, "sk", PRICES,
                                         httpx.AsyncClient(transport=httpx.MockTransport(tavily)),
                                         tavily_key="tvly-REAL", search_price_usd=0.01))
    h = {"Authorization": f"Bearer {key}"}
    r = client.post("/v1/search", headers=h, json={"query": "Acme", "max_results": 50})
    assert r.json()["results"] == [{"title": "T", "url": "U", "snippet": "C"}]
    assert seen[0]["api_key"] == "tvly-REAL" and seen[0]["max_results"] == 10   # 封顶
    assert store.get("a@x.com").spent_usd == pytest.approx(0.01)
    client.post("/v1/search", headers=h, json={"query": "Acme"})                 # 余额 0.005 → 还能搜
    r = client.post("/v1/search", headers=h, json={"query": "Acme"})             # 透支后拒
    assert r.status_code == 400 and "Budget" in r.text and len(seen) == 2


def test_gateway_pages_follow_language(store):
    c = _client(store, _fly([]), _upstream([]))
    assert "Continue with Google" in c.get("/", headers={"Accept-Language": "en-US"}).text
    assert "用 Google 登录" in c.get("/", headers={"Accept-Language": "zh-CN"}).text
    r = c.get("/_gw/lang?to=en", follow_redirects=False)
    assert r.status_code == 302 and "jl_lang=en" in r.headers["set-cookie"]
    c.cookies.set("jl_lang", "en")
    assert "Continue with Google" in c.get("/", headers={"Accept-Language": "zh-CN"}).text
    c.cookies.set("jl_state", "a")
    assert "Sign-in failed" in c.get("/auth/callback?code=c&state=b").text
    store.create("a@x.com", 2.0)
    c2 = _client(store, _fly([]), _upstream([]), "a@x.com")
    assert "Setting up your private space" in c2.get("/", headers={"Accept-Language": "en"}).text


def test_reset_destroys_and_reprovisions(store):
    import time
    store.create("a@x.com", 2.0)
    store.charge("a@x.com", "m-pro", 0, 0, 0.5)
    store.set_status("a@x.com", "ready", machine_id="m_old", volume_id="vol_old")
    old_token = store.get("a@x.com").gateway_token
    calls = []
    c = _client(store, _fly(calls), _upstream([]), "a@x.com")
    assert c.post("/_gw/reset", data={"confirm": "nope"}).json() == {"error": "confirm"}
    assert c.post("/_gw/reset", data={"confirm": "RESET"},
                  headers={"Origin": "https://evil.example"}).status_code == 403
    assert store.get("a@x.com").machine_id == "m_old"            # 前两次都没动
    assert c.post("/_gw/reset", data={"confirm": "RESET"},
                  headers={"Origin": "https://app.test"}).json() == {"ok": True}
    for _ in range(50):
        if store.get("a@x.com").status == "new":
            break
        time.sleep(0.02)
    u = store.get("a@x.com")
    assert (u.status, u.machine_id, u.volume_id) == ("new", None, None)
    assert u.gateway_token != old_token
    assert u.spent_usd == 0.5 and u.credit_usd == 2.0              # 额度不随重置回血
    assert ("DELETE", "/v1/apps/users/machines/m_old", None) in calls
    assert ("DELETE", "/v1/apps/users/volumes/vol_old", None) in calls
    assert "准备独立空间" in c.get("/").text                        # 下次访问 = 新用户开通


def test_cli_reset_runs(store, tmp_path, monkeypatch):
    """管理命令 reset 走得通（曾因函数定义在入口之后而 NameError——网页路径的测试覆盖不到）。"""
    import runpy, sys
    store.create("a@x.com", 1.0)
    store.set_status("a@x.com", "ready", machine_id="m1", volume_id="v1")
    calls = []
    monkeypatch.setenv("GW_DB", store.db.execute("PRAGMA database_list").fetchone()[2])
    monkeypatch.setenv("FLY_API_TOKEN", "tok")
    import gw.flyapi as F
    orig = F.Fly.__init__
    transport = httpx.MockTransport(lambda req: calls.append((req.method, req.url.path)) or httpx.Response(200, json={}))
    def fake_init(self, token, app, region, client=None):
        orig(self, token, app, region, httpx.AsyncClient(transport=transport))
    monkeypatch.setattr(F.Fly, "__init__", fake_init)
    monkeypatch.setattr(sys, "argv", ["gw.cli", "reset", "a@x.com"])
    runpy.run_module("gw.cli", run_name="__main__")
    assert store.get("a@x.com").machine_id is None
    assert {m for m, *_ in calls} == {"DELETE"}


def test_landing_language_choice_reaches_engine_once(store):
    store.create("a@x.com", 2.0)
    store.set_status("a@x.com", "ready", machine_id="m_1")
    seen = []
    c = _client(store, _fly([]), _upstream(seen), "a@x.com")
    r = c.get("/_gw/lang?to=en", follow_redirects=False)
    assert "jl_lang_set=en" in str(r.headers.get_list("set-cookie"))
    c.get("/", headers={"X-Joblander-Set-Lang": "zh"})          # 客户端自带的同名头被丢弃
    assert seen[-1].headers["x-joblander-set-lang"] == "en"
    assert "jl_lang_set" not in c.cookies                         # 送达后即清掉
    c.get("/")
    assert "x-joblander-set-lang" not in seen[-1].headers


def test_reset_form_parses_in_real_dependency_set():
    """/_gw/reset 用表单：python-multipart 必须在网关依赖里（线上曾因缺它 500）。"""
    from pathlib import Path
    req = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
    assert "python-multipart" in req


def test_feedback_stored_emailed_and_rate_limited(store):
    store.create("a@x.com", 1.0)
    sent = []
    def handler(req: httpx.Request):
        sent.append(json.loads(req.content)); return httpx.Response(200, json={"id": "e1"})
    s = Settings(**{**SETTINGS.__dict__, "feedback_to": "boss@x.com", "resend_api_key": "re_x"})
    app = create_web_app(s, store, _fly([]), _upstream([]))
    c = TestClient(app, base_url="https://app.test")
    c.cookies.set("jl_session", make_session("s", "a@x.com"))
    # 邮件走网关里的共享 httpx client：替换它的 transport
    import httpx as _h
    orig = _h.AsyncClient.post
    async def fake_post(self, url, **kw):
        if "resend" in str(url):
            return handler(_h.Request("POST", url, json=kw.get("json")))
        return await orig(self, url, **kw)
    _h.AsyncClient.post = fake_post
    try:
        assert c.post("/_gw/feedback", data={"message": "x"}).json() == {"error": "empty"}
        r = c.post("/_gw/feedback", data={"message": "The brief button is slow\nmore detail",
                                          "page": "/company/1", "lang": "en"},
                   headers={"Origin": "https://app.test", "User-Agent": "UA"})
        assert r.json() == {"ok": True}
        assert sent[0]["to"] == ["boss@x.com"] and sent[0]["reply_to"] == "a@x.com"
        assert sent[0]["subject"] == "[joblander feedback] The brief button is slow"
        assert store.list_feedback()[0]["emailed"] == 1
        assert c.post("/_gw/feedback", data={"message": "hi"}, headers={"Origin": "https://evil.example"}).status_code == 403
        for _ in range(9):
            c.post("/_gw/feedback", data={"message": "again"})
        assert c.post("/_gw/feedback", data={"message": "again"}).json() == {"error": "rate"}
    finally:
        _h.AsyncClient.post = orig


def test_feedback_kept_when_email_not_configured(store):
    store.create("a@x.com", 1.0)
    c = _client(store, _fly([]), _upstream([]), "a@x.com")
    assert c.post("/_gw/feedback", data={"message": "works offline"}).json() == {"ok": True}
    f = store.list_feedback()[0]
    assert f["message"] == "works offline" and f["emailed"] == 0


# ---------- 隐私：同意、导出、彻底删除 ----------

def test_privacy_page_is_public_and_landing_links_it(store):
    c = _client(store, _fly([]), _upstream([]))
    r = c.get("/_gw/privacy")
    assert r.status_code == 200 and "OpenAI" in r.text and "30 天" in r.text
    assert "Privacy notice" in c.get("/_gw/privacy?lang=en").text
    assert "/_gw/privacy" in c.get("/").text


def test_no_provisioning_before_consent(store):
    import time
    store.create("a@x.com", 2.0)
    calls = []
    c = _client(store, _fly(calls), _upstream([]), "a@x.com", consent=False)
    r = c.get("/")
    assert "/_gw/consent" in r.text and "准备独立空间" not in r.text
    assert c.get("/api/whatever").status_code == 403
    assert c.get("/_gw/status").json()["status"] == "consent"
    time.sleep(0.05)
    assert calls == [] and store.get("a@x.com").status == "new"        # 没同意就不开卷、不开机器
    assert c.post("/_gw/consent", headers={"Origin": "https://evil.example"}).status_code == 403
    r = c.post("/_gw/consent", headers={"Origin": "https://app.test"}, follow_redirects=False)
    assert r.status_code == 303 and store.get("a@x.com").privacy_version
    assert "准备独立空间" in c.get("/").text                             # 同意后才开通


def test_export_has_records_but_no_credentials(store):
    store.create("a@x.com", 2.0)
    store.charge("a@x.com", "m-pro", 10, 5, 0.01)
    store.add_feedback("a@x.com", "hello", "/", "zh", "ua")
    c = _client(store, _fly([]), _upstream([]), "a@x.com")
    r = c.get("/_gw/export")
    assert "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["account"]["email"] == "a@x.com" and len(data["usage"]) == 1
    assert data["feedback"][0]["message"] == "hello"
    raw = r.text
    u = store.get("a@x.com")
    assert u.gateway_token not in raw and u.meter_key_hash not in raw


def test_delete_destroys_machine_and_all_records(store):
    import time
    store.invite("a@x.com")
    store.create("a@x.com", 2.0)
    store.charge("a@x.com", "m-pro", 0, 0, 0.5)
    store.add_feedback("a@x.com", "hi", "/", "zh", "ua")
    store.set_status("a@x.com", "ready", machine_id="m_old", volume_id="vol_old")
    store.create("b@x.com", 2.0)
    calls = []
    c = _client(store, _fly(calls), _upstream([]), "a@x.com")
    assert c.post("/_gw/delete", data={"confirm": "RESET"}).json() == {"error": "confirm"}
    assert c.post("/_gw/delete", data={"confirm": "DELETE"},
                  headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/_gw/delete", data={"confirm": "DELETE"},
                  headers={"Origin": "https://app.test"}).json() == {"ok": True}
    for _ in range(50):
        if store.get("a@x.com") is None:
            break
        time.sleep(0.02)
    assert store.get("a@x.com") is None and not store.is_invited("a@x.com")
    for t in ("usage", "grants", "feedback"):
        assert store.db.execute(f"SELECT COUNT(*) FROM {t} WHERE email='a@x.com'").fetchone()[0] == 0
    assert store.get("b@x.com") is not None                              # 别人不受影响
    assert ("DELETE", "/v1/apps/users/machines/m_old", None) in calls
    assert ("DELETE", "/v1/apps/users/volumes/vol_old", None) in calls
    assert c.get("/", follow_redirects=False).headers["location"] == "/auth/logout"


def test_access_log_has_no_paths(store, caplog):
    import logging
    store.create("a@x.com", 2.0)
    store.set_status("a@x.com", "ready", machine_id="m_1")
    c = _client(store, _fly([]), _upstream([]), "a@x.com")
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        c.get("/wsdoc/18-companies/SecretCo/brief.md")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "GET page 200" in text and "SecretCo" not in text


# ---------- 给用户本人的通知邮件 ----------

def _resend_mock(monkeypatch, mails, who="friend@x.com"):
    def handler(req: httpx.Request):
        if "resend" in req.url.host:
            mails.append(json.loads(req.content))
            return httpx.Response(200, json={"id": "e"})
        if "token" in req.url.path:
            return httpx.Response(200, json={"access_token": "at"})
        return httpx.Response(200, json={"email": who, "email_verified": True})
    orig = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: orig(transport=httpx.MockTransport(handler)))


def test_blocked_person_gets_confirmation_when_domain_configured(store, monkeypatch):
    mails = []
    _resend_mock(monkeypatch, mails)
    s = Settings(**{**SETTINGS.__dict__, "feedback_to": "boss@x.com", "resend_api_key": "re_x",
                    "mail_from": "joblander <hello@ailayoff.me>"})
    c = TestClient(create_web_app(s, store, _fly([]), _upstream([])), base_url="https://app.test")
    c.cookies.set("jl_state", "st"); c.cookies.set("jl_lang", "en")
    assert "sent a confirmation" in c.get("/auth/callback?code=c&state=st", follow_redirects=False).text
    to_admin, to_user = mails
    assert to_admin["to"] == ["boss@x.com"] and to_admin["from"] == "joblander <onboarding@resend.dev>"
    assert to_user["to"] == ["friend@x.com"] and to_user["from"] == "joblander <hello@ailayoff.me>"
    assert to_user["reply_to"] == "boss@x.com" and to_user["subject"] == "We've got your beta request"


def test_invite_cli_emails_person_in_their_language(store, monkeypatch, capsys):
    import runpy, sys
    mails = []
    _resend_mock(monkeypatch, mails)
    monkeypatch.setenv("GW_DB", store.db.execute("PRAGMA database_list").fetchone()[2])
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    monkeypatch.setenv("MAIL_FROM", "joblander <hello@ailayoff.me>")
    monkeypatch.setenv("FEEDBACK_TO", "boss@x.com")
    store.record_blocked("friend@x.com", "en")
    monkeypatch.setattr(sys, "argv", ["gw.cli", "invite", "Friend@x.com", "new@x.com"])
    runpy.run_module("gw.cli", run_name="__main__")
    assert [m["to"] for m in mails] == [["friend@x.com"], ["new@x.com"]]
    assert mails[0]["subject"] == "You're in — joblander beta"            # 被拦时是英文界面
    assert "/" in mails[1]["subject"] and "已加入内测" in mails[1]["html"]   # 语言未知：中英都放
    assert "https://app.ailayoff.me" in mails[0]["html"] and mails[0]["reply_to"] == "boss@x.com"
    assert store.is_invited("friend@x.com") and store.waitlist() == []
    monkeypatch.setattr(sys, "argv", ["gw.cli", "invite", "q@x.com", "--quiet"])
    runpy.run_module("gw.cli", run_name="__main__")
    assert len(mails) == 2 and store.is_invited("q@x.com")


def test_low_balance_reminder_fires_once_until_topped_up(store):
    _, key = store.create("a@x.com", 1.0)
    store.charge("a@x.com", "m-pro", 0, 0, 0.4999)                      # 余额 0.5001，还没跌破
    fired: list = []

    async def on_low(email):
        fired.append(email)
    client = TestClient(create_meter_app(store, "sk", PRICES,
                                         httpx.AsyncClient(transport=httpx.MockTransport(_openai([]))),
                                         low_balance_usd=0.5, on_low=on_low))
    for _ in range(2):
        assert client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                           json={"model": "m-pro"}).status_code == 200
    assert fired == ["a@x.com"]                                          # 跌破只提醒一次
    store.grant("a@x.com", 1.0, "续")
    assert store.get("a@x.com").low_notified_at is None                  # 加额度后重新武装
    assert store.charge("a@x.com", "m-pro", 0, 0, 1.2, low_at=0.5)


def test_user_mail_templates_escape_and_fall_back_to_both_languages():
    from gw.notify import render_user
    subj, body = render_user("low_balance", None, email="<x>@y.com", balance="0.42")
    assert subj == "你的 AI 额度快用完了 / Your AI credit is running low"
    assert "$0.42" in body and "<x>" not in body


# ---------- 管理后台 ----------

def test_admin_portal_is_admin_only_and_shows_numbers(store):
    store.create("boss@x.com", 2.0)
    store.create("a@x.com", 2.0)
    store.charge("a@x.com", "m-pro", 1000, 200, 1.7)
    store.record_blocked("<script>@x.com", "en")
    store.add_feedback("a@x.com", "按钮点不动", "/pipeline", "zh", "ua")
    anon = _client(store, _fly([]), _upstream([]))
    assert anon.get("/_gw/admin").status_code == 404
    assert _client(store, _fly([]), _upstream([]), "a@x.com").get("/_gw/admin").status_code == 404
    c = _client(store, _fly([]), _upstream([]), "boss@x.com")
    r = c.get("/_gw/admin")
    assert r.status_code == 200
    for s in ("a@x.com", "$1.70", "m-pro", "按钮点不动", "被拦的登录", "&lt;script&gt;@x.com"):
        assert s in r.text, s
    assert "<script>@x.com" not in r.text                                     # 名单里的邮箱要转义
    assert 'class="n low">$0.30' in r.text                                    # 低于提醒线标红
    assert "gateway_token" not in r.text and store.get("a@x.com").gateway_token not in r.text
    assert c.get("/_gw/me").json()["admin"] is True                          # 应用里的「后台」入口靠这个
    assert _client(store, _fly([]), _upstream([]), "a@x.com").get("/_gw/me").json()["admin"] is False


def test_admin_actions_invite_dismiss_grant(store):
    store.create("boss@x.com", 2.0)
    store.create("a@x.com", 2.0)
    store.record_blocked("w@x.com", "zh")
    store.record_blocked("spam@x.com", "zh")
    c = _client(store, _fly([]), _upstream([]), "boss@x.com")
    r = c.post("/_gw/admin/invite", data={"email": "W@x.com"}, follow_redirects=False)
    assert r.status_code == 303 and store.is_invited("w@x.com")
    assert [w["email"] for w in store.waitlist()] == ["spam@x.com"]
    c.post("/_gw/admin/dismiss", data={"email": "spam@x.com"})
    assert store.waitlist() == []
    r = c.post("/_gw/admin/grant", data={"email": "a@x.com", "usd": "5"}, follow_redirects=True)
    assert store.get("a@x.com").credit_usd == 7.0 and "已给 a@x.com 加 $5" in r.text
    c.post("/_gw/admin/grant", data={"email": "a@x.com", "usd": "500"})                # 超上限不加
    c.post("/_gw/admin/grant", data={"email": "nobody@x.com", "usd": "5"})
    assert store.get("a@x.com").credit_usd == 7.0 and store.get("nobody@x.com") is None
    # 非管理员与跨站请求一律拒
    u = _client(store, _fly([]), _upstream([]), "a@x.com")
    assert u.post("/_gw/admin/grant", data={"email": "a@x.com", "usd": "5"}).status_code == 404
    assert c.post("/_gw/admin/grant", data={"email": "a@x.com", "usd": "5"},
                  headers={"Origin": "https://evil.test"}).status_code == 404
    assert store.get("a@x.com").credit_usd == 7.0
