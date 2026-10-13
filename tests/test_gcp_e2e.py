"""GCP 形态端到端：真实的网关（共享引擎后端）+ 真实的引擎与任务服务，同进程经 ASGI 连起来。

覆盖：首次登录自动开通账户 → 转发带账户令牌 → 两个用户的数据互不可见 → 浏览器自带的令牌头被丢弃
→ 删除账户连同引擎里的数据一起删掉。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("maxminddb")                       # 网关依赖（CI 的引擎测试步骤一并安装）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud" / "gateway"))

from gw import pages  # noqa: E402
from gw.shared import SharedEngine  # noqa: E402
from gw.store import Store  # noqa: E402
from gw.web import Settings, create_web_app, make_session  # noqa: E402

from joblander import tasks, tenancy  # noqa: E402
from joblander.cloud import backend  # noqa: E402
from joblander.storage.memfs import MemoryStore  # noqa: E402

SECRET = "e" * 40
ENGINE, WORKER = "https://engine.test", "https://worker.test"


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBLANDER_MODE", "multi")
    monkeypatch.setenv("JOBLANDER_STORE", "memory")
    monkeypatch.setenv("JOBLANDER_TENANT_TOKEN_SECRET", SECRET)
    monkeypatch.setenv("JOBLANDER_ALLOWED_HOSTS", "app.test")
    monkeypatch.setenv("JOBLANDER_TASKS_SYNC", "1")
    monkeypatch.delenv("JOBLANDER_GATEWAY_TOKEN", raising=False)
    backend.install(MemoryStore())
    from joblander.cloud.engine import create_engine_app
    from joblander.cloud.worker import create_worker_app
    client = httpx.AsyncClient(mounts={
        ENGINE: httpx.ASGITransport(app=create_engine_app()),
        WORKER: httpx.ASGITransport(app=create_worker_app()),
    }, timeout=30)
    store = Store(str(tmp_path / "gw.sqlite"))
    settings = Settings(public_host="app.test", session_secret="s" * 32, google_client_id="x",
                        google_client_secret="y", user_image="", meter_url=f"{ENGINE}/v1")
    engine = SharedEngine(ENGINE, WORKER, SECRET, client=client)
    app = create_web_app(settings, store, engine, client)
    yield store, settings, app
    tenancy.set_lock_backend(None)
    tasks.set_table(tasks.MemoryTable())
    backend._store = None


def _login(store, settings, app, email):
    store.create(email, 2.0)
    store.consent(email, pages.PRIVACY_VERSION)
    c = TestClient(app, base_url="https://app.test")
    c.cookies.set("jl_session", make_session(settings.session_secret, email))
    for _ in range(50):                                   # 首次访问触发开通，等到就绪
        st = c.get("/_gw/status").json()
        if st.get("status") == "ready":
            return c
        time.sleep(0.05)
    raise AssertionError(f"开通没完成：{st} / {store.get(email).error}")


def test_first_login_provisions_and_proxies(stack):
    store, settings, app = stack
    c = _login(store, settings, app, "a@x.com")
    tid = store.get("a@x.com").volume_id
    assert tid and backend.store().has_tenant(tid)        # 网关里的「卷」就是引擎里的账户
    r = c.get("/settings")
    assert r.status_code == 200 and "joblander" in r.text.lower()


def test_two_users_are_isolated_end_to_end(stack):
    store, settings, app = stack
    a = _login(store, settings, app, "a@x.com")
    _login(store, settings, app, "b@x.com")
    assert a.post("/api/settings/lang", data={"lang": "en"}, headers={"origin": "https://app.test"}).status_code == 200
    ta, tb = store.get("a@x.com").volume_id, store.get("b@x.com").volume_id
    assert ta != tb
    assert backend.tenant_config(ta).raw.get("ui_lang") == "en"
    assert backend.tenant_config(tb).raw.get("ui_lang") != "en"


def test_browser_supplied_tenant_token_is_dropped(stack):
    store, settings, app = stack
    a = _login(store, settings, app, "a@x.com")
    _login(store, settings, app, "b@x.com")
    from gw.shared import tenant_token
    forged = tenant_token(store.get("b@x.com").volume_id, SECRET)     # 就算拿到了 B 的有效令牌
    a.post("/api/settings/lang", data={"lang": "en"},
           headers={"origin": "https://app.test", "x-joblander-tenant-token": forged})
    assert backend.tenant_config(store.get("a@x.com").volume_id).raw.get("ui_lang") == "en"
    assert backend.tenant_config(store.get("b@x.com").volume_id).raw.get("ui_lang") != "en"


def test_delete_account_removes_engine_data(stack):
    store, settings, app = stack
    c = _login(store, settings, app, "a@x.com")
    tid = store.get("a@x.com").volume_id
    r = c.post("/_gw/delete", data={"confirm": "DELETE"}, headers={"origin": "https://app.test"})
    assert r.json() == {"ok": True}
    for _ in range(50):
        if store.get("a@x.com") is None:
            break
        time.sleep(0.05)
    assert store.get("a@x.com") is None and not backend.store().has_tenant(tid)


def test_privacy_v2_switch_reaches_engine(stack, monkeypatch):
    """网关按开关与退出期给引擎打「能不能记」的标；引擎只在标为 on 时记路由模板，关掉立即停。"""
    from gw import privacy_v2

    from joblander import telemetry
    from joblander.obs import user_key
    store, settings, app = stack
    monkeypatch.setattr(pages, "PRIVACY_VERSION", privacy_v2.VERSION)
    monkeypatch.setattr(privacy_v2, "effective_ts", lambda: 0.0)     # 当作 v2 生效后注册的新用户
    monkeypatch.setenv("OPENAI_BASE_URL", f"{ENGINE}/v1")
    monkeypatch.setenv("JOBLANDER_EVENTS_TOPIC", "projects/p/topics/events")
    monkeypatch.setattr(telemetry, "_events_started", True)
    monkeypatch.setattr(telemetry, "_events", [])
    c = _login(store, settings, app, "a@x.com")
    c.get("/sourcing", headers={"x-joblander-analytics": "off"})
    tid = store.get("a@x.com").volume_id
    assert [(e["route"], e["user_key"]) for e in telemetry._events] == [("/sourcing", user_key(tid))]
    c.post("/_gw/analytics", data={"on": "0"}, headers={"origin": "https://app.test"})
    c.get("/sourcing", headers={"x-joblander-analytics": "on"})        # 浏览器自己带 on 也没用
    assert len(telemetry._events) == 1
    telemetry.drain()
