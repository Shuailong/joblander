"""云端版的产品使用记录：每个请求记「方法 + 路由模板 + 时间」，每分钟打包报给网关（计量口），供后台画转化漏斗与功能使用。

只记路由模板（如 `GET /company/{page_id}`），不记具体路径、参数、表单或任何内容；
本机版（没有网关）完全不记。报失败就丢，不重试——这是统计，不是账本。
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

_buf: list[tuple[str, float]] = []
_lock = threading.Lock()
_started = False


def enabled() -> bool:
    return bool(os.environ.get("JOBLANDER_GATEWAY_TOKEN") and os.environ.get("OPENAI_BASE_URL"))


def record(method: str, route: str | None, now: float | None = None) -> None:
    if not route or route.startswith(SKIP_PREFIX):
        return
    name = f"{method} {route}"
    if name in SKIP:
        return
    with _lock:
        if len(_buf) < MAX_BUFFER:
            _buf.append((name, now or time.time()))


def drain() -> list[tuple[str, float]]:
    with _lock:
        out = list(_buf)
        _buf.clear()
    return out


def flush() -> int:
    events = drain()
    if not events:
        return 0
    url = os.environ["OPENAI_BASE_URL"].rstrip("/") + "/events"
    req = urllib.request.Request(
        url, data=json.dumps({"events": [{"name": n, "at": t} for n, t in events]}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:                                   # noqa: BLE001  统计丢了就丢了
        return 0
    return len(events)


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
