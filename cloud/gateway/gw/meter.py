"""计量代理：用户 machine 拿子 key 调这里（OpenAI 兼容），这里查余额 → 转发 OpenAI → 按用量记账。

- 只监听私网端口（fly.toml 不暴露），公网打不到
- 余额 ≤ 0 直接拒；拒绝正文带 "budget exceeded"——引擎侧据此转成「额度已用完」提示
- 价目表未知的模型一律拒（fail closed）：宁可报错，不可无限花钱
- 记账发生在流结束后，并发请求可能让余额小幅透支（一次调用的量级），可接受
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from gw.store import Store

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def _reject(msg: str, status: int = 400, kind: str = "invalid_request") -> JSONResponse:
    return JSONResponse({"error": {"message": msg, "type": kind}}, status_code=status)


def cost_usd(prices: dict, model: str, prompt: int, completion: int) -> float:
    p = prices[model]
    return (prompt * p["input"] + completion * p["output"]) / 1_000_000


TAVILY_URL = "https://api.tavily.com/search"


def create_meter_app(store: Store, openai_key: str, prices: dict,
                     client: httpx.AsyncClient | None = None, *,
                     tavily_key: str = "", search_price_usd: float = 0.01,
                     low_balance_usd: float | None = None,
                     on_low: Callable[[str], Awaitable[None]] | None = None) -> FastAPI:
    app = FastAPI(title="joblander-meter")
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10))
    pending: set[asyncio.Task] = set()

    def charge(email: str, model: str, pt: int, ct: int, cost: float) -> None:
        """记账；余额首次跌破提醒线时异步发提醒（发信失败不影响计量）。"""
        if store.charge(email, model, pt, ct, cost, low_at=low_balance_usd if on_low else None):
            t = asyncio.create_task(on_low(email))
            pending.add(t)
            t.add_done_callback(pending.discard)

    @app.post("/v1/search")
    async def search(request: Request):
        """公司调研的搜索：平台 Tavily key 只在这里；按次计费，与 AI 共用一份额度。"""
        auth = request.headers.get("authorization") or ""
        user = store.by_meter_key(auth.removeprefix("Bearer ").strip()) if auth else None
        if user is None:
            return _reject("unknown key", 401, "auth")
        if not tavily_key:
            return _reject("search not configured", 503)
        if user.balance_usd <= 0:
            return _reject(f"Budget has been exceeded: balance {user.balance_usd:.4f} USD",
                           400, "budget_exceeded")
        body = await request.json()
        q = str(body.get("query") or "").strip()[:400]
        if not q:
            return _reject("empty query", 400)
        n = max(1, min(int(body.get("max_results") or 6), 10))
        r = await http.post(TAVILY_URL, json={"api_key": tavily_key, "query": q, "max_results": n})
        if r.status_code >= 400:
            return _reject(f"search upstream {r.status_code}", 502)
        charge(user.email, "search:tavily", 0, 0, search_price_usd)
        return {"results": [{"title": x.get("title", ""), "url": x.get("url", ""),
                             "snippet": (x.get("content") or "")[:800]}
                            for x in r.json().get("results", [])][:n]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        auth = request.headers.get("authorization") or ""
        user = store.by_meter_key(auth.removeprefix("Bearer ").strip()) if auth else None
        if user is None:
            return _reject("unknown key", 401, "auth")
        if user.balance_usd <= 0:
            return _reject(f"Budget has been exceeded: balance {user.balance_usd:.4f} USD",
                           400, "budget_exceeded")
        body = await request.json()
        model = body.get("model") or ""
        if model not in prices:
            return _reject(f"model not allowed: {model}", 400)
        stream = bool(body.get("stream"))
        if stream:                                   # 没有 usage 就没法记账：强制要
            body["stream_options"] = {"include_usage": True}
        headers = {"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"}

        if not stream:
            r = await http.post(OPENAI_URL, json=body, headers=headers)
            out = r.json()
            u = out.get("usage") or {}
            if r.status_code < 400:
                pt, ct = u.get("prompt_tokens") or 0, u.get("completion_tokens") or 0
                charge(user.email, model, pt, ct, cost_usd(prices, model, pt, ct))
            return JSONResponse(out, status_code=r.status_code)

        req = http.build_request("POST", OPENAI_URL, json=body, headers=headers)
        upstream = await http.send(req, stream=True)
        if upstream.status_code >= 400:
            text = await upstream.aread()
            await upstream.aclose()
            return JSONResponse(json.loads(text or b"{}"), status_code=upstream.status_code)

        async def relay():
            usage: dict = {}
            buf = b""
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        if line.startswith(b"data: ") and b'"usage"' in line:
                            try:
                                usage = json.loads(line[6:]).get("usage") or usage
                            except json.JSONDecodeError:
                                pass
            finally:
                await upstream.aclose()
                pt, ct = usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0
                if pt or ct:
                    charge(user.email, model, pt, ct, cost_usd(prices, model, pt, ct))

        return StreamingResponse(relay(), status_code=upstream.status_code,
                                 media_type="text/event-stream")

    return app
