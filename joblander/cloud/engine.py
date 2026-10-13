"""引擎服务（JOBLANDER_ROLE=engine）：用户界面与 API，所有账户共享。

入口：uvicorn --factory joblander.cloud.engine:create_engine_app
每个请求必须带网关签发的账户令牌（X-Joblander-Tenant-Token）；验过才把该账户放进上下文，
下游的 cfg、workspace、任务托盘、锁全都只看得到这一个账户。没有令牌或令牌不对一律 401。
"""

from __future__ import annotations

import json
from typing import Any

from joblander import isolation
from joblander.cloud import backend, tokens
from joblander.tenancy import use_tenant

HEADER = b"x-joblander-tenant-token"
OPEN_PATHS = ("/static/",)          # 静态资源不含账户数据


class TenantMiddleware:
    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path == "/healthz":
            return await _json(send, 200, {"ok": True})
        if path.startswith(OPEN_PATHS):
            return await self.app(scope, receive, send)
        token = next((v.decode() for k, v in scope.get("headers", []) if k == HEADER), "")
        try:
            tenant_id = tokens.verify(token)
        except tokens.TokenError as e:
            if token:                              # 有令牌却验不过：可能是伪造，记一笔
                isolation.violation("token", str(e))
            return await _json(send, 401, {"error": "需要经登录网关访问"})
        if not backend.store().has_tenant(tenant_id):
            return await _json(send, 404, {"error": "账户不存在或已删除"})
        from joblander import telemetry
        # 隐私 v2：网关按这个账户的开关与退出期决定能不能记行为数据（浏览器自带的同名头网关会丢掉）
        telemetry.set_analytics(any(k == b"x-joblander-analytics" and v == b"on"
                                    for k, v in scope.get("headers", [])))
        with use_tenant(backend.tenant(tenant_id)):
            await self.app(scope, receive, send)


async def _json(send: Any, status: int, body: dict) -> None:
    data = json.dumps(body, ensure_ascii=False).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json; charset=utf-8"),
                            (b"content-length", str(len(data)).encode())]})
    await send({"type": "http.response.body", "body": data})


def create_engine_app() -> Any:
    import os
    os.environ.setdefault("JOBLANDER_MODE", "multi")
    backend.store()                                # 装配后端：账户锁与任务表接到数据库
    from joblander.web.app import create_app
    return TenantMiddleware(create_app(with_daemon=False))
