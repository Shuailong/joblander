"""网关进程。

Fly 形态（默认）：同一个进程起两个端口。
- 8080 公网（fly.toml 的 services 只暴露它）：登录、开 machine、转发
- 8081 私网（不暴露）：计量代理，只有用户 machine 经 joblander-gw.internal 访问得到

GCP 形态（GW_MODE=gcp）：网关与计量拆成两个 Cloud Run 服务，按 GW_ROLE 只起一个（端口用 $PORT）：
- web：登录、同意、后台、转发到共享引擎（带账户令牌）
- meter：计量代理（只接受引擎与任务服务的调用，账户由请求头指明）
状态在 Cloud SQL（GW_DB_HOST / NAME / USER / PASSWORD），多实例时后台循环只由领头实例跑。
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import httpx
import uvicorn

from gw.flyapi import Fly
from gw.meter import create_meter_app
from gw.notify import send_ai_alert, send_budget_alert
from gw.store import Store
from gw.web import Settings, create_web_app


def env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise SystemExit(f"缺环境变量 {name}")
    return v


def gcp() -> bool:
    return os.environ.get("GW_MODE") == "gcp"


def db_target() -> str:
    """Fly：卷上的 SQLite 文件；GCP：Cloud SQL 私有 IP 上的 Postgres。"""
    if not gcp():
        return env("GW_DB", "/data/gw.sqlite")
    from psycopg.conninfo import make_conninfo
    return make_conninfo(host=env("GW_DB_HOST"), port=os.environ.get("GW_DB_PORT", "5432"),
                         dbname=os.environ.get("GW_DB_NAME", "gateway"),
                         user=os.environ.get("GW_DB_USER", "gateway"), password=env("GW_DB_PASSWORD"),
                         sslmode=os.environ.get("GW_DB_SSLMODE", "require"))


def build():
    store = Store(db_target())
    prices = json.loads(env("MODEL_PRICES"))    # {"gpt-x": {"input": 每百万 token 美元, "output": ...}}
    for m, p in prices.items():
        if not {"input", "output"} <= set(p):
            raise SystemExit(f"MODEL_PRICES 里 {m} 缺 input/output 单价")
    if gcp():
        from gw.shared import PgLeader, SharedEngine
        fly = SharedEngine(env("ENGINE_URL"), env("WORKER_URL"), env("JOBLANDER_TENANT_TOKEN_SECRET"))
    else:
        fly = Fly(env("FLY_API_TOKEN"), env("USER_APP", "joblander-users"), env("FLY_REGION", "sin"))
    settings = Settings(
        public_host=env("PUBLIC_HOST"),
        session_secret=env("SESSION_SECRET"),
        google_client_id=env("GOOGLE_CLIENT_ID"),
        google_client_secret=env("GOOGLE_CLIENT_SECRET"),
        user_image=env("USER_IMAGE", "" if gcp() else None),
        meter_url=env("METER_URL", "http://joblander-gw.internal:8081/v1"),
        free_credit_usd=float(env("FREE_CREDIT_USD", "2")),
        memory_mb=int(env("USER_MEMORY_MB", "1024")),
        admins={e.strip().lower() for e in env("ADMIN_EMAILS", "").split(",") if e.strip()},
        feedback_to=env("FEEDBACK_TO", env("ADMIN_EMAILS", "").split(",")[0].strip()),
        resend_api_key=env("RESEND_API_KEY", ""),
        mail_from=env("MAIL_FROM", ""),
        low_balance_usd=float(env("LOW_BALANCE_USD", "0.5")),
        idle_minutes=0 if gcp() else int(env("IDLE_MINUTES", "15")),     # 共享引擎没有机器可睡
        wake_at=env("WAKE_AT", "02:35,08:20,21:35,sun 20:05"),
        digest_at=env("DIGEST_AT", "09:00"),
        mail_daily_limit=int(env("MAIL_DAILY_LIMIT", "90")),
        monthly_budget_usd=float(env("MONTHLY_BUDGET_USD", "0")),
    )
    if settings.mail_from:                   # 有了已验证域名，给管理员的通知也用它发
        settings.feedback_from = settings.mail_from
    if gcp():
        settings.leader = PgLeader(db_target())
        topic = os.environ.get("EVENTS_TOPIC", "")
        if topic:                                # 隐私 v2 的行为数据：会话事件进 Pub/Sub → BigQuery
            from gw.events import Publisher, SessionEvents
            settings.events = SessionEvents(Publisher(topic), tz=settings.timezone)
    web = create_web_app(settings, store, fly)
    if gcp():                                    # 隐私 v2 的保存期限：领头实例每天清理（见 gw/events.py）
        from gw.events import Sweeper
        sweeper = Sweeper(store, os.environ.get("EVENTS_TABLE") or None, leader=settings.leader)

        async def start_sweeper():
            web.state.sweeper_task = asyncio.create_task(sweeper.run())
        web.router.on_startup.append(start_sweeper)
    mail_http = httpx.AsyncClient(timeout=15)

    async def on_low(email: str) -> None:
        u = store.get(email)                                    # 进发信队列，和别的信一起按每日上限发
        store.enqueue_mail(email, "low_balance", store.mail_lang(email),
                           {"balance": f"{max(u.balance_usd, 0) if u else 0:.2f}"})

    alerted: dict[str, float] = {}

    async def on_error(status: int, kind: str) -> None:
        """同一类上游错误 3 小时内最多告警一次。"""
        now = time.time()
        if now - alerted.get(kind, 0) < 3 * 3600:
            return
        alerted[kind] = now
        recent = sum(1 for e in store.ai_errors_since(now - 3600) if e["kind"] == kind)
        try:
            await send_ai_alert(mail_http, settings.resend_api_key, settings.feedback_to,
                                sender=settings.feedback_from, status=status, kind=kind, recent=recent)
        except Exception:                                       # noqa: BLE001
            pass

    async def on_budget(level: float, spent: float, budget: float) -> None:
        try:
            await send_budget_alert(mail_http, settings.resend_api_key, settings.feedback_to,
                                    sender=settings.feedback_from, level=level, spent=spent, budget=budget)
        except Exception:                                       # noqa: BLE001
            pass

    if gcp() and os.environ.get("GW_ROLE") == "web":
        return web, None                     # 计量是另一个服务：上游 key 不进网关
    meter = create_meter_app(store, env("OPENAI_API_KEY"), prices,
                             tavily_key=env("TAVILY_API_KEY", ""),
                             search_price_usd=float(env("SEARCH_PRICE_USD", "0.01")),
                             low_balance_usd=settings.low_balance_usd,
                             on_low=on_low if settings.mail_from else None, on_error=on_error,
                             timezone=settings.timezone, trust_tenant_header=gcp(),
                             monthly_budget_usd=settings.monthly_budget_usd, on_budget=on_budget)
    return web, meter


async def serve() -> None:
    if gcp():                                # Cloud Run：一个服务一个端口
        role = os.environ.get("GW_ROLE", "web")
        web, meter = build()
        app = web if role == "web" else meter
        port = int(os.environ.get("PORT", "8080"))
        await uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, proxy_headers=True,
                                            forwarded_allow_ips="*", access_log=False)).serve()
        return
    web, meter = build()
    # 公网口给 Fly 入口代理（走 IPv4）；计量口只给私网（6PN 是 IPv6）——绑 :: 在 Fly 上是 v6-only
    servers = [uvicorn.Server(uvicorn.Config(web, host="0.0.0.0", port=8080, proxy_headers=True,
                                             forwarded_allow_ips="*", access_log=False)),
               uvicorn.Server(uvicorn.Config(meter, host="::", port=8081, access_log=False))]
    # access 日志器是全局共享的：任一 Config 开着就会把它重新装回去，两边都得关
    await asyncio.gather(*(s.serve() for s in servers))


if __name__ == "__main__":
    asyncio.run(serve())
