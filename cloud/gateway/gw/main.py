"""网关进程：同一个进程起两个端口。

- 8080 公网（fly.toml 的 services 只暴露它）：登录、开 machine、转发
- 8081 私网（不暴露）：计量代理，只有用户 machine 经 joblander-gw.internal 访问得到
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import uvicorn

from gw.flyapi import Fly
from gw.meter import create_meter_app
from gw.notify import send_user
from gw.store import Store
from gw.web import Settings, create_web_app


def env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise SystemExit(f"缺环境变量 {name}")
    return v


def build():
    store = Store(env("GW_DB", "/data/gw.sqlite"))
    prices = json.loads(env("MODEL_PRICES"))    # {"gpt-x": {"input": 每百万 token 美元, "output": ...}}
    for m, p in prices.items():
        if not {"input", "output"} <= set(p):
            raise SystemExit(f"MODEL_PRICES 里 {m} 缺 input/output 单价")
    fly = Fly(env("FLY_API_TOKEN"), env("USER_APP", "joblander-users"), env("FLY_REGION", "sin"))
    settings = Settings(
        public_host=env("PUBLIC_HOST"),
        session_secret=env("SESSION_SECRET"),
        google_client_id=env("GOOGLE_CLIENT_ID"),
        google_client_secret=env("GOOGLE_CLIENT_SECRET"),
        user_image=env("USER_IMAGE"),
        meter_url=env("METER_URL", "http://joblander-gw.internal:8081/v1"),
        free_credit_usd=float(env("FREE_CREDIT_USD", "2")),
        memory_mb=int(env("USER_MEMORY_MB", "1024")),
        admins={e.strip().lower() for e in env("ADMIN_EMAILS", "").split(",") if e.strip()},
        feedback_to=env("FEEDBACK_TO", env("ADMIN_EMAILS", "").split(",")[0].strip()),
        resend_api_key=env("RESEND_API_KEY", ""),
        mail_from=env("MAIL_FROM", ""),
        low_balance_usd=float(env("LOW_BALANCE_USD", "0.5")),
    )
    if settings.mail_from:                   # 有了已验证域名，给管理员的通知也用它发
        settings.feedback_from = settings.mail_from
    web = create_web_app(settings, store, fly)
    mail_http = httpx.AsyncClient(timeout=15)

    async def on_low(email: str) -> None:
        u = store.get(email)
        try:
            await send_user(mail_http, settings.resend_api_key, settings.mail_from, settings.feedback_to,
                            to=email, kind="low_balance", lang=u.lang if u else None,
                            balance=f"{max(u.balance_usd, 0) if u else 0:.2f}")
        except Exception:                                       # noqa: BLE001  提醒失败不影响计量
            pass

    meter = create_meter_app(store, env("OPENAI_API_KEY"), prices,
                             tavily_key=env("TAVILY_API_KEY", ""),
                             search_price_usd=float(env("SEARCH_PRICE_USD", "0.01")),
                             low_balance_usd=settings.low_balance_usd,
                             on_low=on_low if settings.mail_from else None)
    return web, meter


async def serve() -> None:
    web, meter = build()
    # 公网口给 Fly 入口代理（走 IPv4）；计量口只给私网（6PN 是 IPv6）——绑 :: 在 Fly 上是 v6-only
    servers = [uvicorn.Server(uvicorn.Config(web, host="0.0.0.0", port=8080, proxy_headers=True,
                                             forwarded_allow_ips="*", access_log=False)),
               uvicorn.Server(uvicorn.Config(meter, host="::", port=8081, access_log=False))]
    # access 日志器是全局共享的：任一 Config 开着就会把它重新装回去，两边都得关
    await asyncio.gather(*(s.serve() for s in servers))


if __name__ == "__main__":
    asyncio.run(serve())
