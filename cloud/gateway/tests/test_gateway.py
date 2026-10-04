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


def _client(store, fly, upstream, email=None):
    c = TestClient(create_web_app(SETTINGS, store, fly, upstream), base_url="https://app.test")
    if email:
        c.cookies.set("jl_session", make_session("s", email))
    return c


def test_anonymous_sees_login_and_api_gets_401(store):
    c = _client(store, _fly([]), _upstream([]))
    assert "用 Google 登录" in c.get("/").text
    assert c.get("/_gw/static/command-center.jpg").status_code == 200
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
