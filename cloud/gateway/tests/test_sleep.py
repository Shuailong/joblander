"""闲置休眠：没人用且引擎不忙才挂起；有请求 / 到定时点就叫醒；网关重启后能自己找回状态。"""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from gw.flyapi import Fly
from gw.sleep import Sleeper, parse_wake
from gw.store import Store
from gw.web import Settings, create_web_app, make_session

TZ = "Asia/Singapore"


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "gw.sqlite"))
    for i, e in enumerate(("a@x.com", "b@x.com")):
        s.create(e, 2.0)
        s.set_status(e, "ready", machine_id=f"m{i}")
    return s


class FakeFly:
    """记下调用，并模拟每台机器的状态。suspend_fails=True 时挂起报错（老机器）。"""

    def __init__(self, states=None, suspend_fails=False):
        self.states = states or {}
        self.calls: list[tuple[str, str]] = []
        self.suspend_fails = suspend_fails

    def handler(self, req: httpx.Request):
        p = req.url.path
        mid = p.split("/machines/")[1].split("/")[0] if "/machines/" in p else ""
        act = p.rsplit("/", 1)[-1]
        self.calls.append((req.method, act if act != mid else "get", mid))
        if act == "suspend":
            if self.suspend_fails:
                return httpx.Response(400, json={"error": "machine not eligible for suspend"})
            self.states[mid] = "suspended"
        elif act == "stop":
            self.states[mid] = "stopped"
        elif act == "start":
            self.states[mid] = "started"
        elif act == mid:
            return httpx.Response(200, json={"id": mid, "state": self.states.get(mid, "started")})
        return httpx.Response(200, json={})

    def client(self):
        return Fly("tok", "users", "sin", httpx.AsyncClient(transport=httpx.MockTransport(self.handler)))

    def acts(self, kind):
        return [m for _, a, m in self.calls if a == kind]


def _engine(busy: dict, seen: list | None = None):
    def handler(req: httpx.Request):
        if seen is not None:
            seen.append(req)
        if req.headers.get("host") != "app.test":               # 跟真引擎一样：Host 不对就 421
            return httpx.Response(421, json={"error": "bad host"})
        if req.url.path == "/api/busy":
            mid = req.url.host.split(".")[0]
            return httpx.Response(200, json={"busy": busy.get(mid, False)})
        return httpx.Response(200, html="<h1>ok</h1>")
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _sleeper(store, fly, busy=None, now=1000.0):
    return Sleeper(store, fly.client(), _engine(busy or {}), idle_minutes=15, wake_at="02:35,sun 20:05",
                   tz=TZ, public_host="app.test", now=now)


def test_parse_wake():
    assert parse_wake("02:35, 08:20,sun 20:05") == [(None, 2, 35), (None, 8, 20), (6, 20, 5)]


def test_idle_machines_sleep_but_busy_or_recent_ones_dont(store):
    fly = FakeFly()
    s = _sleeper(store, fly, busy={"m1": True})
    s.seen("a@x.com", 1000)
    assert asyncio.run(s.reap(1000 + 10 * 60)) == []                    # 还没到 15 分钟
    assert asyncio.run(s.reap(1000 + 16 * 60)) == ["a@x.com"]           # b 在跑任务，不睡
    assert fly.acts("suspend") == ["m0"] and s.asleep == {"a@x.com"}
    assert asyncio.run(s.reap(1000 + 20 * 60)) == []                    # b 忙 → 当作刚用过，再等一轮


def test_suspend_unsupported_falls_back_to_stop(store):
    fly = FakeFly(suspend_fails=True)
    s = _sleeper(store, fly)
    asyncio.run(s.reap(1000 + 16 * 60))
    assert fly.acts("stop") == ["m0", "m1"] and s.asleep == {"a@x.com", "b@x.com"}


def test_scheduled_wake_fires_once_per_slot(store):
    fly = FakeFly({"m0": "suspended", "m1": "suspended"})
    s = _sleeper(store, fly)
    s.asleep = {"a@x.com", "b@x.com"}
    tz = ZoneInfo(TZ)
    at = datetime(2026, 10, 13, 2, 40, tzinfo=tz).timestamp()           # 周二 02:40：02:35 的点到了
    assert s.due_wakes(at) == ["2026-10-13 02:35"]
    assert s.due_wakes(at + 60) == []                                   # 同一个点只叫一次
    assert s.due_wakes(datetime(2026, 10, 13, 20, 10, tzinfo=tz).timestamp()) == []   # 周日的点，周二不叫
    assert s.due_wakes(datetime(2026, 10, 18, 20, 10, tzinfo=tz).timestamp()) == ["2026-10-18 20:05"]
    assert s.due_wakes(datetime(2026, 10, 14, 3, 30, tzinfo=tz).timestamp()) == []    # 过了窗口不补
    asyncio.run(s.wake_all())
    assert fly.acts("start") == ["m0", "m1"] and s.asleep == set()


def test_init_learns_who_is_asleep(store):
    fly = FakeFly({"m0": "suspended", "m1": "started"})
    s = _sleeper(store, fly)
    asyncio.run(s.init())
    assert s.asleep == {"a@x.com"}


# ---------- 接进网关：请求先叫醒再转发；连不上时自己查状态 ----------

SETTINGS = Settings(public_host="app.test", session_secret="s", google_client_id="c",
                    google_client_secret="x", user_image="img", meter_url="http://m/v1", idle_minutes=15)


def _client(store, fly, upstream):
    from gw.pages import PRIVACY_VERSION
    store.consent("a@x.com", PRIVACY_VERSION)
    app = create_web_app(SETTINGS, store, fly.client(), upstream)
    c = TestClient(app, base_url="https://app.test")
    c.cookies.set("jl_session", make_session("s", "a@x.com"))
    return app, c


def test_request_wakes_sleeping_machine_before_forwarding(store):
    fly = FakeFly({"m0": "suspended"})
    seen: list = []
    app, c = _client(store, fly, _engine({}, seen))
    app.state.sleeper.asleep.add("a@x.com")
    r = c.post("/api/x", data={"k": "v"})
    assert r.status_code == 200 and fly.acts("start") == ["m0"]
    assert "a@x.com" not in app.state.sleeper.asleep and seen[-1].content == b"k=v"


def test_unknown_sleep_is_recovered_on_connect_error(store):
    """网关重启后不知道 a 在睡：第一次连不上 → 问 Fly → 叫醒 → 重发。"""
    fly = FakeFly({"m0": "suspended"})
    tries = []

    def handler(req: httpx.Request):
        tries.append(1)
        if fly.states.get("m0") != "started":
            raise httpx.ConnectError("refused")
        return httpx.Response(200, html="<h1>ok</h1>")
    app, c = _client(store, fly, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    r = c.get("/")
    assert r.status_code == 200 and "ok" in r.text and len(tries) == 2 and fly.acts("start") == ["m0"]


def test_admin_shows_asleep(store):
    from gw.pages import PRIVACY_VERSION
    store.create("boss@x.com", 2.0)
    s = Settings(**{**SETTINGS.__dict__, "admins": {"boss@x.com"}})
    app = create_web_app(s, store, FakeFly().client(), _engine({}))
    app.state.sleeper.asleep.add("a@x.com")
    c = TestClient(app, base_url="https://app.test")
    c.cookies.set("jl_session", make_session("s", "boss@x.com"))
    store.consent("boss@x.com", PRIVACY_VERSION)
    html = c.get("/_gw/admin").text
    assert "休眠" in html and "1 / 2" in html and "机器在线" in html
