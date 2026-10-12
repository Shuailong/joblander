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


def _wait(cond, tries: int = 100):
    import time
    for _ in range(tries):
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("等不到")


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


def test_blocked_login_sends_no_mail_but_lands_in_daily_digest(store, monkeypatch):
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
    app = create_web_app(s, store, _fly([]), _upstream([]))
    c = TestClient(app, base_url="https://app.test")
    for _ in range(3):
        c.cookies.set("jl_state", "st")
        assert "已经收到通知" in c.get("/auth/callback?code=c&state=st", follow_redirects=False).text
    assert mails == []                                           # 被拦当场不发信（量大会撞 Resend 上限）
    assert [(w["email"], w["attempts"]) for w in store.waitlist()] == [("friend@x.com", 3)]
    import asyncio
    assert asyncio.run(app.state.send_digest()) is True          # 每天一封汇总给管理员
    assert len(mails) == 1 and mails[0]["to"] == ["boss@x.com"]
    assert "1 人申请" in mails[0]["subject"] and "friend@x.com" in mails[0]["html"]
    assert asyncio.run(app.state.send_digest()) is None and len(mails) == 1     # 没有新内容就不发
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
                                       "credit_usd": 2.0, "spent_usd": 1.75, "low": True, "request": None}
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
        assert sent == [] and store.list_feedback()[0]["emailed"] == 0          # 不逐条发信
        import asyncio
        asyncio.run(app.state.send_digest())
        assert sent[0]["to"] == ["boss@x.com"] and "1 条反馈" in sent[0]["subject"]
        assert "The brief button is slow" in sent[0]["html"] and "a@x.com" in sent[0]["html"]
        assert store.list_feedback()[0]["emailed"] == 1                         # 已进汇总
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


def test_blocked_person_gets_no_auto_reply_even_with_domain(store, monkeypatch):
    mails = []
    _resend_mock(monkeypatch, mails)
    s = Settings(**{**SETTINGS.__dict__, "feedback_to": "boss@x.com", "resend_api_key": "re_x",
                    "mail_from": "joblander <hello@ailayoff.me>"})
    c = TestClient(create_web_app(s, store, _fly([]), _upstream([])), base_url="https://app.test")
    c.cookies.set("jl_state", "st"); c.cookies.set("jl_lang", "en")
    r = c.get("/auth/callback?code=c&state=st", follow_redirects=False).text
    assert "you'll get an email at this address once you're in" in r and "confirmation" not in r
    assert mails == []                                           # 不给每个申请人发回执，也不逐条通知管理员


def test_invite_cli_queues_mail_in_persons_language(store, monkeypatch, capsys):
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
    assert mails == []                                                   # 不直接发：进网关的发信队列
    q = [store.next_mail()]
    store.mail_done(q[0]["id"])
    q.append(store.next_mail())
    assert [(m["to_email"], m["kind"], m["lang"]) for m in q] == [("friend@x.com", "invited", "en"),  # 被拦时是英文界面
                                                                  ("new@x.com", "invited", None)]
    assert store.is_invited("friend@x.com") and store.waitlist() == []
    from gw.notify import render_user
    subj, body = render_user("invited", None, email="new@x.com")
    assert "/" in subj and "已加入内测" in body and "https://app.ailayoff.me" in body   # 语言未知：中英都放
    assert render_user("invited", "en", email="a@x.com")[0] == "You're in — joblander beta"
    monkeypatch.setattr(sys, "argv", ["gw.cli", "invite", "q@x.com", "--quiet"])
    runpy.run_module("gw.cli", run_name="__main__")
    assert store.mail_stats(0)["pending"] == 1 and store.is_invited("q@x.com")


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
    assert store.get("a@x.com").credit_usd == 7.0 and "已给 a•••@x.com 加 $5" in r.text
    c.post("/_gw/admin/grant", data={"email": "a@x.com", "usd": "500"})                # 超上限不加
    c.post("/_gw/admin/grant", data={"email": "nobody@x.com", "usd": "5"})
    assert store.get("a@x.com").credit_usd == 7.0 and store.get("nobody@x.com") is None
    # 非管理员与跨站请求一律拒
    u = _client(store, _fly([]), _upstream([]), "a@x.com")
    assert u.post("/_gw/admin/grant", data={"email": "a@x.com", "usd": "5"}).status_code == 404
    assert c.post("/_gw/admin/grant", data={"email": "a@x.com", "usd": "5"},
                  headers={"Origin": "https://evil.test"}).status_code == 404
    assert store.get("a@x.com").credit_usd == 7.0


def test_home_screen_icons_are_public(store):
    """存到手机主屏幕：未登录也能拿到 PNG 图标与 manifest（iOS 不认 SVG，抓图标不一定带 cookie）。"""
    c = _client(store, _fly([]), _upstream([]))
    assert 'rel="apple-touch-icon" href="/_gw/static/icon-180.png"' in c.get("/").text
    r = c.get("/_gw/static/icon-180.png")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    m = c.get("/_gw/static/manifest.webmanifest")
    assert m.status_code == 200 and m.json()["icons"][0]["src"] == "/_gw/static/icon-192.png"


def test_admin_masks_emails_and_charts_growth_and_tokens(store):
    from gw.admin import mask
    assert mask("liangshuailong@gmail.com") == "li•••g@gmail.com" and mask("ab@x.com") == "a•••@x.com"
    store.create("boss@x.com", 2.0)
    store.create("alice.wong@x.com", 2.0)
    store.set_status("alice.wong@x.com", "ready", machine_id="m_1")
    store.charge("alice.wong@x.com", "m-pro", 1234, 567, 0.42)
    store.add_feedback("alice.wong@x.com", "hi", "/", "zh", "ua")
    u = _client(store, _fly([]), _upstream([]), "alice.wong@x.com")
    u.get("/")
    u.get("/pipeline")
    assert len(store.export("alice.wong@x.com")["active_days"]) == 1        # 每天只记一条，只记日期
    r = _client(store, _fly([]), _upstream([]), "boss@x.com").get("/_gw/admin")
    assert "用户增长" in r.text and "每日活跃" in r.text and "每日 token 与花费" in r.text
    assert "b|输入 1,234 token" in r.text and "a|输出 567 token" in r.text and "l|花费 $0.420" in r.text
    assert "a|已注册 2" in r.text and "className='tip'" in r.text
    assert "al•••g@x.com" in r.text
    assert ">alice.wong@x.com<" not in r.text                                 # 只在表单的隐藏字段里出现全名
    store.delete_user("alice.wong@x.com")
    assert store.db.execute("SELECT COUNT(*) FROM active_days").fetchone()[0] == 0


def test_credit_request_flow(store, monkeypatch):
    mails = []

    async def fake_post(self, url, **kw):
        mails.append(kw["json"])
        return httpx.Response(200)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(SETTINGS, "resend_api_key", "re_x")
    monkeypatch.setattr(SETTINGS, "mail_from", "joblander <hi@x.com>")
    monkeypatch.setattr(SETTINGS, "feedback_to", "boss@x.com")
    monkeypatch.setattr(SETTINGS, "digest_at", "")              # 别让每日汇总在测试里插一封
    store.create("boss@x.com", 2.0)
    store.create("a@x.com", 2.0)
    store.charge("a@x.com", "m-pro", 0, 0, 1.9)
    u = _client(store, _fly([]), _upstream([]), "a@x.com")
    ok = {"Origin": "https://app.test"}
    assert u.post("/_gw/credit-request", data={"message": "多给点"}, headers=ok).json() == {"error": "short"}
    assert u.post("/_gw/credit-request", data={"message": "x" * 20},
                  headers={"Origin": "https://evil.example"}).status_code == 403
    out = u.post("/_gw/credit-request", data={"message": "在投三家公司，尽调很好用；希望简历定制能更快"}, headers=ok).json()
    assert out["ok"] and out["request"]["status"] == "pending"
    assert u.post("/_gw/credit-request", data={"message": "再来一次申请更多的额度"}, headers=ok).json() == {"error": "pending"}
    assert u.get("/_gw/me").json()["request"]["status"] == "pending"
    assert mails == []                                           # 申请不逐条发信，进每日汇总
    from gw.notify import render_digest
    subject, body = render_digest(store.digest_since(0), day="2026-10-13")
    assert "1 条额度申请" in subject and "尽调很好用" in body and "a@x.com" in body

    rid = out["request"]["id"]
    assert u.post("/_gw/admin/request", data={"id": rid, "usd": "5", "action": "approve"}).status_code == 404
    boss = TestClient(create_web_app(SETTINGS, store, _fly([]), _upstream([])), base_url="https://app.test")
    boss.__enter__()                                             # 同一个事件循环：排队的邮件才发得出去
    boss.cookies.set("jl_session", make_session("s", "boss@x.com"))
    store.consent("boss@x.com", __import__("gw.pages").pages.PRIVACY_VERSION)
    page = boss.get("/_gw/admin").text
    assert 'id="requests"' in page and "尽调很好用" in page and "a•••@x.com" in page
    r = boss.post("/_gw/admin/request", data={"id": rid, "usd": "5", "action": "approve"}, follow_redirects=True)
    assert "已批：给 a•••@x.com 加 $5" in r.text
    assert store.get("a@x.com").credit_usd == 7.0
    _wait(lambda: mails)
    assert mails[-1]["to"] == ["a@x.com"] and "$5" in mails[-1]["html"] and "$5.10" in mails[-1]["html"]
    assert u.get("/_gw/me").json()["request"]["status"] == "approved"
    r = boss.post("/_gw/admin/request", data={"id": rid, "usd": "5", "action": "approve"}, follow_redirects=True)
    assert "已处理过" in r.text and store.get("a@x.com").credit_usd == 7.0            # 不会重复发
    # 批完可以再申请；不批不发额度
    rid2 = u.post("/_gw/credit-request", data={"message": "还想再多一点额度试试"}, headers=ok).json()["request"]["id"]
    boss.post("/_gw/admin/request", data={"id": rid2, "usd": "5", "action": "decline"})
    assert store.get("a@x.com").credit_usd == 7.0
    assert u.get("/_gw/me").json()["request"]["status"] == "declined"
    assert len(store.export("a@x.com")["credit_requests"]) == 2
    store.delete_user("a@x.com")
    assert store.db.execute("SELECT COUNT(*) FROM credit_requests").fetchone()[0] == 0
    boss.__exit__(None, None, None)


def test_growth_counts_blocked_and_invited(store):
    store.create("boss@x.com", 2.0)
    store.record_blocked("w1@x.com", "zh")
    store.record_blocked("w2@x.com", "zh")
    store.invite("w2@x.com")                                   # 被拦后获邀：仍记得首次被拦的时间
    store.invite("fresh@x.com")
    store.record_blocked("spam@x.com", "en")
    store.dismiss("spam@x.com")                                # 清掉的不计
    assert store.db.execute("SELECT requested_at FROM invites WHERE email='w2@x.com'").fetchone()[0]
    html = _client(store, _fly([]), _upstream([]), "boss@x.com").get("/_gw/admin").text
    assert "a|已注册 1\nb|已邀请未登录 2\nc|被拦待处理 1\n|累计 4" in html


def test_meter_records_upstream_failures_and_alerts(store):
    _, key = store.create("a@x.com", 5.0)
    store.create("boss@x.com", 2.0)
    alerts = []

    async def on_error(status, kind):
        alerts.append((status, kind))

    def handler(req: httpx.Request):
        return httpx.Response(429, json={"error": {"message": "slow down", "type": "requests",
                                                   "code": "rate_limit_exceeded"}})
    client = TestClient(create_meter_app(store, "sk", PRICES, httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                                         on_error=on_error))
    for stream in (True, False):
        r = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                        json={"model": "m-pro", "stream": stream, "messages": []})
        assert r.status_code == 429 and "rate_limit_exceeded" in r.text      # 原样回给引擎，引擎据此退避重试
    errs = store.ai_errors_since(0)
    assert [(e["status"], e["kind"]) for e in errs] == [(429, "rate_limit_exceeded")] * 2
    assert alerts == [(429, "rate_limit_exceeded")] * 2                   # 去重在 main.on_error 里做
    assert store.get("a@x.com").spent_usd == 0
    html = _client(store, _fly([]), _upstream([]), "boss@x.com").get("/_gw/admin").text
    assert "AI 调用失败" in html and "rate_limit_exceeded" in html and "24 小时 AI 失败" in html


def test_usage_events_feed_funnel_and_features(store):
    import time as _t
    now = _t.time()
    _, key = store.create("a@x.com", 2.0)
    store.create("b@x.com", 2.0)
    store.create("boss@x.com", 2.0)
    store.invite("c@x.com")                                       # 获邀未注册
    store.record_blocked("d@x.com", "en")                         # 被拦
    from gw.pages import PRIVACY_VERSION
    for e in ("a@x.com", "b@x.com"):
        store.consent(e, PRIVACY_VERSION)
    client = TestClient(create_meter_app(store, "sk", PRICES, httpx.AsyncClient(transport=httpx.MockTransport(_openai([])))))
    evs = [{"name": "GET /sourcing", "at": now}, {"name": "POST /api/setup/resume", "at": now},
           {"name": "POST /api/proposal/apply", "at": now}, {"name": "GET /sourcing", "at": now},
           {"name": "GET /company/Acme Secret", "at": now},           # 夹带具体值：丢
           {"name": "rm -rf", "at": now}, {"name": "GET /", "at": now - 30 * 86400}]   # 格式不对 / 太旧：丢
    r = client.post("/v1/events", headers={"Authorization": f"Bearer {key}"}, json={"events": evs})
    assert r.json() == {"ok": True, "n": 4}
    assert client.post("/v1/events", headers={"Authorization": "Bearer nope"}, json={"events": evs}).status_code == 401
    rows = store.db.execute("SELECT name, n FROM events WHERE email='a@x.com' ORDER BY name").fetchall()
    assert [tuple(r) for r in rows] == [("GET /sourcing", 2), ("POST /api/proposal/apply", 1), ("POST /api/setup/resume", 1)]
    store.charge("b@x.com", "m-pro", 1, 1, 0.01)                  # b 没有使用记录、但用过 AI：前面各步补齐

    html = _client(store, _fly([]), _upstream([]), "boss@x.com").get("/_gw/admin").text
    assert "转化漏斗" in html and "功能使用" in html and "新用户回访" in html
    from gw import bi
    from zoneinfo import ZoneInfo
    b = bi.compute(store.admin_snapshot(0), ZoneInfo("Asia/Singapore"), now)
    f = dict(b["funnel"])
    assert f["来过（被拦 / 获邀 / 注册）"] == 5 and f["注册"] == 3 and f["同意隐私说明"] == 3      # 管理员也同意过
    assert f["看过新机会"] == 2 and f["用上 AI"] == 2 and f["批准第一条机会进作战室"] == 1
    assert ("新机会", "GET /sourcing", 1, 2) in b["features"]
    assert "Acme" not in html


# ---------- 后台：分页 / 批量 / 地理 ----------

def _boss(store, monkeypatch=None, mail=False):
    """管理员客户端；mail=True 时配好发信并进入同一个事件循环（排队的邮件才发得出去）。"""
    s = Settings(**{**SETTINGS.__dict__, "digest_at": "", "mail_gap_s": 0,
                    **({"resend_api_key": "re_x", "mail_from": "joblander <hi@x.com>", "feedback_to": "boss@x.com"}
                       if mail else {})})
    c = TestClient(create_web_app(s, store, _fly([]), _upstream([])), base_url="https://app.test")
    if mail:
        c.__enter__()
    if not store.get("boss@x.com"):
        store.create("boss@x.com", 2.0)
    from gw.pages import PRIVACY_VERSION
    store.consent("boss@x.com", PRIVACY_VERSION)
    c.cookies.set("jl_session", make_session("s", "boss@x.com"))
    return c


def test_admin_tables_paginate_and_search(store):
    for i in range(120):
        store.create(f"user{i:03d}@x.com", 2.0)
    for i in range(60):
        store.record_blocked(f"wait{i:02d}@x.com", "zh")
    c = _boss(store)
    p1 = c.get("/_gw/admin").text
    assert "第 1–50 条 · 共 121 条" in p1 and "第 1–50 条 · 共 60 条" in p1
    assert 'href="?pu=3#users"' in p1 and "<b>1</b>" in p1
    p3 = c.get("/_gw/admin?pu=3").text
    assert "第 101–121 条 · 共 121 条" in p3
    assert c.get("/_gw/admin?pu=999").status_code == 200 and "第 101–121 条" in c.get("/_gw/admin?pu=999").text
    assert "第 1–50 条" in c.get("/_gw/admin?pu=abc").text                     # 乱写页码当第一页
    q = c.get("/_gw/admin?q=user007").text
    assert 'value="user007@x.com"' in q and 'value="user008@x.com"' not in q and "没有匹配的人" in q
    # 操作完回到原来那页、原来的搜索
    r = c.post("/_gw/admin/dismiss", data={"email": "wait00@x.com", "ret": "pw=2&q=wait&evil=1"},
               follow_redirects=False)
    loc = r.headers["location"]
    assert loc.startswith("/_gw/admin?pw=2&q=wait&m=") and loc.endswith("#waitlist") and "evil" not in loc


def test_admin_bulk_invite_and_dismiss_waitlist(store, monkeypatch):
    mails, broken = [], {"w2@x.com"}

    async def fake_post(self, url, **kw):
        mails.append(kw["json"])
        return httpx.Response(500 if kw["json"]["to"][0] in broken else 200)    # w2 一直发不出去
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    for e in ("w1@x.com", "w2@x.com", "w3@x.com", "spam1@x.com", "spam2@x.com"):
        store.record_blocked(e, "en")
    c = _boss(store, mail=True)
    page = c.get("/_gw/admin").text
    assert 'action="/_gw/admin/waitlist"' in page and 'name="sel" value="w1@x.com"' in page
    r = c.post("/_gw/admin/waitlist", data={"act": "invite", "sel": ["w1@x.com", "W2@x.com", "w3@x.com"]},
               follow_redirects=True)
    assert "已邀请 3 人" in r.text and "3 封邀请邮件已排队" in r.text
    assert all(store.is_invited(e) for e in ("w1@x.com", "w2@x.com", "w3@x.com"))
    _wait(lambda: store.mail_stats(0) == {"pending": 0, "sent": 2, "failed": 1})
    assert sum(m["to"] == ["w2@x.com"] for m in mails) == 5                   # 失败重试 5 次后放弃
    assert mails[0]["subject"] == "You're in — joblander beta"
    page = c.get("/_gw/admin").text                                           # 发不出去的标出来
    assert page.count("邮件未发出") == 1 and "重发 1 封没发出的邀请邮件" in page
    assert "24 小时已发 2/90 · 放弃 1" in page
    broken.clear()
    r = c.post("/_gw/admin/resend-invites", follow_redirects=True)
    assert "1 封邀请邮件已重新排队" in r.text
    _wait(lambda: mails[-1]["to"] == ["w2@x.com"] and store.mail_stats(0)["sent"] == 3)
    assert "邮件未发出" not in c.get("/_gw/admin").text
    # 行内按钮只处理那一行；批量清掉
    c.post("/_gw/admin/waitlist", data={"act": "dismiss:spam1@x.com", "sel": ["spam2@x.com"]})
    assert [w["email"] for w in store.waitlist()] == ["spam2@x.com"]
    r = c.post("/_gw/admin/waitlist", data={"act": "dismiss", "sel": ["spam2@x.com"]}, follow_redirects=True)
    assert "已清掉 1 人" in r.text and store.waitlist() == []
    assert "没勾选任何人" in c.post("/_gw/admin/waitlist", data={"act": "invite"}, follow_redirects=True).text
    # 非管理员 / 跨站一律拒
    assert c.post("/_gw/admin/waitlist", data={"act": "invite", "sel": ["x@x.com"]},
                  headers={"Origin": "https://evil.test"}).status_code == 404
    assert not store.is_invited("x@x.com")
    c.__exit__(None, None, None)


def test_admin_bulk_approve_credit_requests(store, monkeypatch):
    mails = []

    async def fake_post(self, url, **kw):
        mails.append(kw["json"])
        return httpx.Response(200)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    ids = {}
    for e in ("a@x.com", "b@x.com", "c@x.com", "d@x.com"):
        store.create(e, 2.0)
        ids[e] = store.request_credit(e, "想多试几家公司的尽调")
    c = _boss(store, mail=True)
    assert 'name="usd_%d"' % ids["a@x.com"] in c.get("/_gw/admin").text
    r = c.post("/_gw/admin/requests", data={"act": "approve", "usd": "3",
                                            "sel": [ids["a@x.com"], ids["b@x.com"]]}, follow_redirects=True)
    assert "已批 2 条，每人加 $3" in r.text and "2 封通知邮件已排队" in r.text
    assert store.get("a@x.com").credit_usd == 5.0 and store.get("b@x.com").credit_usd == 5.0
    _wait(lambda: len(mails) == 2)
    assert sorted(m["to"][0] for m in mails) == ["a@x.com", "b@x.com"]
    # 行内：用那一行自己的金额
    c.post("/_gw/admin/requests", data={"act": f"approve:{ids['c@x.com']}", f"usd_{ids['c@x.com']}": "7",
                                        "usd": "1", "sel": [ids["d@x.com"]]})
    assert store.get("c@x.com").credit_usd == 9.0 and store.get("d@x.com").credit_usd == 2.0
    # 已处理过的跳过，不重复发额度
    r = c.post("/_gw/admin/requests", data={"act": "approve", "usd": "3", "sel": [ids["a@x.com"], ids["d@x.com"]]},
               follow_redirects=True)
    assert "已批 1 条" in r.text and "1 条已处理过，跳过" in r.text
    assert store.get("a@x.com").credit_usd == 5.0 and store.get("d@x.com").credit_usd == 5.0
    assert "没批：金额须在 0–100 之间" in c.post("/_gw/admin/requests", data={
        "act": "approve", "usd": "500", "sel": [ids["a@x.com"]]}, follow_redirects=True).text
    c.__exit__(None, None, None)


def test_geo_recorded_at_login_and_daily_visit_and_shown_masked(store, monkeypatch):
    from gw.geo import Geo, mask_ip
    assert mask_ip("203.0.113.57") == "203.0.113.x" and mask_ip("2001:db8:1:2::5") == "2001:0db8:0001::x"
    assert mask_ip(None) == "—" and mask_ip("junk") == "—"
    assert Geo("/nonexistent.mmdb").lookup("8.8.8.8")["country"] == ""         # 没库：只记 IP
    places = {"1.2.3.4": ("CN", "中国", "Shanghai", "Shanghai", 31.2, 121.4),
              "5.6.7.8": ("SG", "新加坡", "", "Singapore", 1.3, 103.8)}

    def lookup(self, ip):
        c, n, r, city, lat, lon = places.get(ip, ("", "", "", "", None, None))
        return {"country": c, "country_name": n, "region": r, "city": city, "lat": lat, "lon": lon}
    monkeypatch.setattr(Geo, "lookup", lookup)
    seen = []

    def google(req: httpx.Request):
        if "token" in req.url.path:
            return httpx.Response(200, json={"access_token": "at"})
        return httpx.Response(200, json={"email": seen[-1], "email_verified": True})
    import gw.web as W
    orig = httpx.AsyncClient
    monkeypatch.setattr(W.httpx, "AsyncClient", lambda *a, **k: orig(transport=httpx.MockTransport(google)))
    store.create("a@x.com", 2.0)
    c = TestClient(create_web_app(SETTINGS, store, _fly([]), _upstream([])), base_url="https://app.test")
    for who, ip in (("a@x.com", "1.2.3.4"), ("stranger@x.com", "5.6.7.8")):
        seen.append(who)
        c.cookies.set("jl_state", "st")
        c.get("/auth/callback?code=c&state=st", headers={"Fly-Client-IP": ip}, follow_redirects=False)
    g = {r["email"]: r for r in store.admin_snapshot(0)["geo"]}
    assert g["a@x.com"]["city"] == "Shanghai" and g["stranger@x.com"]["country"] == "SG"
    assert store.export("a@x.com")["location"][0]["ip"] == "1.2.3.4"
    page = _boss(store).get("/_gw/admin").text
    assert 'id="geomap"' in page and "用户分布" in page and "DB-IP" in page
    assert "1.2.3.x" in page and "1.2.3.4" not in page                          # IP 打码
    import re
    pts = json.loads(re.search(r'id="geodata">(.*?)</script>', page).group(1))
    assert {(p["city"], p["reg"], p["wl"]) for p in pts} == {("Shanghai", 1, 0), ("Singapore", 0, 1)}
    assert "<td>中国</td>" in page and "<td>新加坡</td>" in page
    # 被拦的人被清掉 / 用户删号：地点一并删
    store.dismiss("stranger@x.com")
    store.delete_user("a@x.com")
    assert store.admin_snapshot(0)["geo"] == []


def test_mail_queue_respects_daily_limit_and_survives_restart(store, monkeypatch):
    mails = []

    async def fake_post(self, url, **kw):
        mails.append(kw["json"])
        return httpx.Response(200)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    # 上次进程排了没发完的信：新进程一启动就接着发
    store.create("a@x.com", 2.0)
    store.enqueue_mail("a@x.com", "credit_granted", "zh", {"amount": "5", "balance": "7.00"})
    s = Settings(**{**SETTINGS.__dict__, "digest_at": "", "mail_gap_s": 0, "mail_daily_limit": 2,
                    "resend_api_key": "re_x", "mail_from": "joblander <hi@x.com>", "feedback_to": "boss@x.com"})
    c = TestClient(create_web_app(s, store, _fly([]), _upstream([])), base_url="https://app.test")
    c.__enter__()
    _wait(lambda: len(mails) == 1)
    assert "$5" in mails[0]["html"] and "$7.00" in mails[0]["html"]
    # 24 小时内最多 2 封：第 3 封顺延
    ids = [store.request_credit(e, "想多试几家公司的尽调") for e in ("b@x.com", "c@x.com") if store.create(e, 2.0)]
    store.create("boss@x.com", 2.0)
    from gw.pages import PRIVACY_VERSION
    store.consent("boss@x.com", PRIVACY_VERSION)
    c.cookies.set("jl_session", make_session("s", "boss@x.com"))
    r = c.post("/_gw/admin/requests", data={"act": "approve", "usd": "3", "sel": ids}, follow_redirects=True)
    assert "已批 2 条" in r.text and store.get("c@x.com").credit_usd == 5.0       # 额度照发，信排队
    _wait(lambda: len(mails) == 2)
    import time
    time.sleep(0.2)
    assert len(mails) == 2 and store.mail_stats(0)["pending"] == 1
    assert "24 小时已发 2/2（已满，顺延）" in c.get("/_gw/admin").text
    # 过了 24 小时腾出名额：接着发
    store.db.execute("UPDATE mail_queue SET sent_at = sent_at - 2 * 86400")
    c.post("/_gw/admin/invite", data={"email": "new@x.com"})                       # 入队会叫醒它
    _wait(lambda: len(mails) == 4)                                                 # 顺延的那封 + 新邀请，又到上限
    assert [m["to"][0] for m in mails[2:]] == ["c@x.com", "new@x.com"]
    c.__exit__(None, None, None)


def test_mail_queue_pauses_on_resend_quota_without_dropping(store, monkeypatch):
    calls = []

    async def fake_post(self, url, **kw):
        calls.append(kw["json"])
        return httpx.Response(429, json={"name": "daily_quota_exceeded", "message": "You have reached your daily quota"})
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    store.record_blocked("w@x.com", "zh")
    c = _boss(store, mail=True)
    c.post("/_gw/admin/waitlist", data={"act": "invite", "sel": ["w@x.com"]})
    _wait(lambda: calls)
    import time
    time.sleep(0.2)
    m = store.next_mail()
    assert len(calls) == 1 and m["status"] == "pending" and m["tries"] == 0      # 额度用完：停下等，不算失败
    c.__exit__(None, None, None)
