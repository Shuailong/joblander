"""云端版的产品使用记录：每个请求记「方法 + 路由模板 + 时间」，每分钟打包报给网关（计量口），供后台画转化漏斗与功能使用。

只记路由模板（如 `GET /company/{page_id}`），不记具体路径、参数、表单或任何内容；
本机版（没有网关）完全不记。报失败就丢，不重试——这是统计，不是账本。
多租户形态下同一进程替很多账户干活：每条记录带上账户，按账户分批上报（账户由请求头指明）。
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

# 轮询、静态资源、文件下载、预览这类请求不算「用户在用某个功能」
SKIP_PREFIX = ("/static", "/files/", "/wsdoc/", "/favicon")
SKIP = {"GET /api/tasks", "GET /api/busy", "POST /api/tasks/dismiss", "POST /api/md/preview",
        "GET /api/company/jd_raw"}
MAX_BUFFER = 2000
FLUSH_EVERY = 60

_buf: list[tuple[str, str, float]] = []        # (账户, 名称, 时间)
_lock = threading.Lock()
_started = False


def enabled() -> bool:
    from joblander import runtime
    return runtime.is_cloud() and bool(os.environ.get("OPENAI_BASE_URL"))


def record(method: str, route: str | None, now: float | None = None) -> None:
    if not route or route.startswith(SKIP_PREFIX):
        return
    name = f"{method} {route}"
    if name in SKIP:
        return
    from joblander.tenancy import tenant_id
    with _lock:
        if len(_buf) < MAX_BUFFER:
            _buf.append((tenant_id(), name, now or time.time()))


def _drain_all() -> list[tuple[str, str, float]]:
    with _lock:
        out = list(_buf)
        _buf.clear()
    return out


def drain() -> list[tuple[str, float]]:
    return [(n, t) for _, n, t in _drain_all()]


def flush() -> int:
    from joblander import runtime
    from joblander.tenancy import Tenant, use_tenant
    by_tenant: dict[str, list[tuple[str, float]]] = {}
    for tid, n, t in _drain_all():
        by_tenant.setdefault(tid, []).append((n, t))
    url = os.environ.get("OPENAI_BASE_URL", "").rstrip("/") + "/events"
    sent = 0
    for tid, events in by_tenant.items():
        with use_tenant(Tenant(tid, None)):             # 上报头里要指明是哪个账户
            headers = {"Content-Type": "application/json", **runtime.upstream_headers(url)}
        req = urllib.request.Request(
            url, data=json.dumps({"events": [{"name": n, "at": t} for n, t in events]}).encode(),
            headers=headers)
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:                               # noqa: BLE001  统计丢了就丢了
            continue
        sent += len(events)
    return sent


def start() -> None:
    """后台线程每分钟报一次；只在云端版启动。"""
    global _started
    if _started or not enabled():
        return
    _started = True

    def loop():
        while True:
            time.sleep(FLUSH_EVERY)
            flush()
    threading.Thread(target=loop, daemon=True, name="telemetry").start()


# ---------- 隐私 v2 的行为数据（只在多租户形态、且网关说这个账户可以记时） ----------
# 每个请求一条：页面模板、状态码、耗时。不记路径、参数与任何内容。按批发到 Pub/Sub → BigQuery。

import contextvars  # noqa: E402

_analytics: contextvars.ContextVar[bool] = contextvars.ContextVar("joblander_analytics", default=False)
_events: list[dict] = []
_events_lock = threading.Lock()
_events_started = False


def set_analytics(on: bool) -> None:
    """引擎的账户中间件按网关给的 x-joblander-analytics 头设置（见 cloud/engine.py）。"""
    _analytics.set(on)


def behavior(method: str, route: str | None, status: int, ms: float, now: float | None = None) -> bool:
    from joblander import runtime
    topic = os.environ.get("JOBLANDER_EVENTS_TOPIC", "")
    if not (runtime.is_multi() and topic and _analytics.get()):
        return False
    if not route or route.startswith(SKIP_PREFIX) or f"{method} {route}" in SKIP:
        return False
    from joblander.obs import user_key
    from joblander.tenancy import tenant_id
    with _events_lock:
        if len(_events) < 5000:
            _events.append({"v": 1, "type": "request", "user_key": user_key(tenant_id()),
                            "at": now or time.time(), "method": method, "route": route,
                            "status": int(status), "ms": round(float(ms), 1)})
    _start_events(topic)
    return True


def flush_behavior(topic: str) -> int:
    with _events_lock:
        batch = _events[:500]
        del _events[:500]
    if not batch:
        return 0
    from joblander import gcp
    try:
        gcp.pubsub_publish(topic, batch)
    except Exception:                                   # noqa: BLE001  统计丢了就丢了
        return 0
    return len(batch)


def _start_events(topic: str) -> None:
    global _events_started
    with _events_lock:
        if _events_started:
            return
        _events_started = True

    def loop():
        while True:
            time.sleep(10)
            while flush_behavior(topic) == 500:
                pass
    threading.Thread(target=loop, daemon=True, name="behavior-events").start()
