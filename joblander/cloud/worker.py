"""任务服务（JOBLANDER_ROLE=worker）：只有内部接口，不对用户开放。

入口：uvicorn --factory joblander.cloud.worker:create_worker_app
调用方与鉴权全靠 Cloud Run IAM：只有网关（开通 / 删除 / 迁移）、Cloud Scheduler（扇出）、
Cloud Tasks（按账户跑一轮）的服务账号有 run.invoker；服务本身只接受内部流量。

调度：Cloud Scheduler 每分钟调一次 /_internal/scheduler/fanout，给每个账户建一个
「跑一轮」的 Cloud Task（按分钟命名去重），任务回调 /_internal/tenants/{id}/tick。
队列的并发与速率上限就是夜扫的削峰阀门（不至于同一刻把 OpenAI 限额打满）。
"""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from joblander.cloud import accounts, backend, tokens
from joblander.tenancy import use_tenant


def _queue() -> dict[str, str] | None:
    q = os.environ.get("JOBLANDER_TASKS_QUEUE", "")
    url = os.environ.get("JOBLANDER_WORKER_URL", "")
    sa = os.environ.get("JOBLANDER_TASKS_SA", "")
    return {"queue": q, "url": url.rstrip("/"), "sa": sa} if q and url and sa else None


def _check_tenant(tenant_id: str) -> JSONResponse | None:
    if not tokens.TENANT_RE.match(tenant_id):
        return JSONResponse({"error": "账户 ID 格式不对"}, status_code=400)
    return None


def run_tick(tenant_id: str) -> bool:
    from joblander.daemon import tick_once
    t = backend.tenant(tenant_id)
    with use_tenant(t):
        return tick_once(t.cfg)


def fanout(now: float | None = None) -> dict[str, Any]:
    """给每个账户投递一轮调度。没配队列（本机 / 测试）就直接逐个跑。"""
    ids = backend.store().tenants()
    q = _queue()
    if q is None:
        ran = sum(1 for tid in ids if run_tick(tid))
        return {"tenants": len(ids), "ran": ran}
    from joblander import gcp
    minute = time.strftime("%Y%m%d%H%M", time.gmtime(now or time.time()))
    created = 0
    for tid in ids:
        if gcp.tasks_create(q["queue"], f"{q['url']}/_internal/tenants/{tid}/tick", {},
                            audience=q["url"], service_account=q["sa"],
                            name=f"tick-{tid}-{minute}", deadline_s=1800):
            created += 1
    return {"tenants": len(ids), "enqueued": created}


def create_worker_app() -> FastAPI:
    os.environ.setdefault("JOBLANDER_MODE", "multi")
    backend.store()
    app = FastAPI(title="joblander-worker", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/_internal/tenants")
    async def create_tenant(request: Request):
        body = await request.json()
        tid = str(body.get("tenant_id") or "")
        if (bad := _check_tenant(tid)) is not None:
            return bad
        return accounts.provision(tid, body.get("lang"))

    @app.delete("/_internal/tenants/{tid}")
    def delete_tenant(tid: str):
        if (bad := _check_tenant(tid)) is not None:
            return bad
        accounts.delete(tid)
        return {"ok": True}

    @app.get("/_internal/tenants/{tid}/export")
    def export_tenant(tid: str):
        if (bad := _check_tenant(tid)) is not None:
            return bad
        if not backend.store().has_tenant(tid):
            return JSONResponse({"error": "账户不存在"}, status_code=404)
        return Response(accounts.export_zip(tid), media_type="application/zip")

    @app.get("/_internal/tenants/{tid}/manifest")
    def manifest(tid: str):
        if (bad := _check_tenant(tid)) is not None:
            return bad
        return accounts.manifest_tenant(tid)

    @app.post("/_internal/tenants/{tid}/import")
    async def import_tenant(tid: str, request: Request):
        """请求体是 Fly 卷的 tar.gz；大于 32MB 的先传到存储桶，用 ?gcs=bucket/name 指过来。"""
        if (bad := _check_tenant(tid)) is not None:
            return bad
        src = request.query_params.get("gcs", "")
        if src:
            from joblander import gcp
            bucket, _, name = src.partition("/")
            data = gcp.gcs_download(bucket, name)
        else:
            data = await request.body()
        return accounts.import_tar(tid, data)

    @app.post("/_internal/scheduler/fanout")
    def scheduler_fanout():
        return fanout()

    @app.post("/_internal/tenants/{tid}/tick")
    def tenant_tick(tid: str):
        if (bad := _check_tenant(tid)) is not None:
            return bad
        if not backend.store().has_tenant(tid):
            return {"ran": False, "reason": "gone"}       # 账户已删：任务直接结束，不重试
        return {"ran": run_tick(tid)}

    return app
