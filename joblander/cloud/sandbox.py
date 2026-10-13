"""沙箱服务（JOBLANDER_ROLE=sandbox）：只做一件事——跑练兵场的用户代码。

入口：uvicorn --factory joblander.cloud.sandbox:create_sandbox_app
部署要求（见 infra/）：独立 Cloud Run 服务、独立且没有任何角色的服务账号、仅内部入口、
只授权引擎调用；全部出网经 VPC 并被防火墙拒绝；环境变量里不放任何密钥。
即便用户代码突破了子进程限制，这台机器上也没有可偷的东西、没有可连的地方。
"""

from __future__ import annotations

from fastapi import FastAPI, Request


def create_sandbox_app() -> FastAPI:
    from joblander.drill import run_drill
    app = FastAPI(title="joblander-sandbox", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/run")
    async def run(request: Request):
        body = await request.json()
        code = str(body.get("code") or "")
        if len(code) > 50_000:
            return {"ok": False, "error": "代码太长"}
        return run_drill(str(body.get("id") or ""), code, hardened=True)

    return app
