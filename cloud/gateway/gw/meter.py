"""计量代理：用户 machine 拿子 key 调这里（OpenAI 兼容），这里查余额 → 转发 OpenAI → 按用量记账。

- 只监听私网端口（fly.toml 不暴露），公网打不到
- 余额 ≤ 0 直接拒；拒绝正文带 "budget exceeded"——引擎侧据此转成「额度已用完」提示
- 价目表未知的模型一律拒（fail closed）：宁可报错，不可无限花钱
- 记账发生在流结束后，并发请求可能让余额小幅透支（一次调用的量级），可接受
- 全局月度预算（MONTHLY_BUDGET_USD）：全平台本月花费到 70% / 90% 各告警一次，到 100% 停掉 AI 与搜索
  （正文带 "platform_budget"，引擎据此提示「平台本月预算已用完」，不当成用户自己的额度）
- 每次调用记下功能标签（引擎带来的 X-Joblander-Feature：路由模板 / 定时作业名）与耗时，后台按功能算花费
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from gw.store import Store

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# 使用记录只收「方法 + 路由模板」：路径里只许出现字母数字与 / _ - . { } :，挡住任何夹带内容的尝试
EVENT_NAME = re.compile(r"(GET|POST|PUT|PATCH|DELETE) /[A-Za-z0-9_/{}:.\-]{0,100}")
# 功能标签：同样只收路由模板，或定时作业名（job:nightly_sourcing）；不合格式的当没带
FEATURE_NAME = re.compile(EVENT_NAME.pattern + r"|job:[a-z_]{1,40}")
BUDGET_LEVELS = (0.7, 0.9, 1.0)


def feature_of(request: Request) -> str | None:
    f = (request.headers.get("x-joblander-feature") or "").strip()
    return f if FEATURE_NAME.fullmatch(f) else None


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
                     on_low: Callable[[str], Awaitable[None]] | None = None,
                     on_error: Callable[[int, str], Awaitable[None]] | None = None,
                     timezone: str = "Asia/Singapore",
                     monthly_budget_usd: float = 0.0,
                     on_budget: Callable[[float, float, float], Awaitable[None]] | None = None) -> FastAPI:
    app = FastAPI(title="joblander-meter")
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10))
    pending: set[asyncio.Task] = set()
    tz = ZoneInfo(timezone)

    def spawn(coro) -> None:
        t = asyncio.create_task(coro)
        pending.add(t)
        t.add_done_callback(pending.discard)

    # ---- 全局月度预算：本月花费缓存 60 秒（多实例时各自定期回库对账），记账时就地累加 ----
    month = {"key": "", "spent": 0.0, "at": 0.0}

    def month_start(now: float) -> tuple[str, float]:
        d = datetime.fromtimestamp(now, tz)
        return d.strftime("%Y-%m"), d.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()

    def month_spent(now: float | None = None) -> float:
        now = now or time.time()
        key, start = month_start(now)
        if month["key"] != key or now - month["at"] > 60:
            month.update(key=key, spent=store.spent_since(start), at=now)
        return month["spent"]

    def paused() -> JSONResponse | None:
        if monthly_budget_usd > 0 and month_spent() >= monthly_budget_usd:
            return _reject("Platform monthly AI budget is used up; AI is paused until the operator raises it",
                           400, "platform_budget")
        return None

    def check_budget_levels() -> None:
        """跨过 70% / 90% / 100% 时各告警一次（按月记在 kv 里，重启不重发）。"""
        if not (monthly_budget_usd > 0 and on_budget):
            return
        spent = month_spent()
        hit = max((lv for lv in BUDGET_LEVELS if spent >= lv * monthly_budget_usd), default=0)
        k = f"budget_alert:{month['key']}"
        if hit > float(store.get_kv(k) or 0):
            store.set_kv(k, str(hit))
            spawn(on_budget(hit, spent, monthly_budget_usd))

    def charge(email: str, model: str, pt: int, ct: int, cost: float,
               feature: str | None = None, t0: float | None = None) -> None:
        """记账；余额首次跌破提醒线时异步发提醒（发信失败不影响计量）。"""
        latency = int((time.monotonic() - t0) * 1000) if t0 else None
        if store.charge(email, model, pt, ct, cost, low_at=low_balance_usd if on_low else None,
                        feature=feature, latency_ms=latency):
            spawn(on_low(email))
        month_spent()                                   # 先确保缓存是本月的，再累加
        month["spent"] += cost
        check_budget_levels()

    def failed(email: str, model: str, status: int, body: bytes | dict | None, feature: str | None = None) -> None:
        """上游失败记一条（状态码 + OpenAI 的错误类型，如 rate_limit_exceeded / insufficient_quota），并通知告警。"""
        try:
            err = (json.loads(body) if isinstance(body, bytes) else body or {}).get("error") or {}
            kind = str(err.get("code") or err.get("type") or "")
        except (ValueError, AttributeError):
            kind = ""
        kind = kind or f"http_{status}"
        store.record_ai_error(email, model, status, kind, feature)
        if on_error:
            spawn(on_error(status, kind))

    @app.post("/v1/events")
    async def events(request: Request):
        """引擎每分钟报一批使用记录（方法 + 路由模板 + 时间），后台画漏斗用。格式不对的条目直接丢。"""
        auth = request.headers.get("authorization") or ""
        user = store.by_meter_key(auth.removeprefix("Bearer ").strip()) if auth else None
        if user is None:
            return _reject("unknown key", 401, "auth")
        try:
            raw = (await request.json()).get("events") or []
        except ValueError:
            return _reject("bad json", 400)
        now = time.time()
        rows = []
        for ev in raw[:2000] if isinstance(raw, list) else []:
            name, at = str((ev or {}).get("name") or ""), (ev or {}).get("at")
            if not EVENT_NAME.fullmatch(name) or not isinstance(at, (int, float)) or not now - 7 * 86400 < at <= now + 300:
                continue
            rows.append((name, datetime.fromtimestamp(at, tz).strftime("%Y-%m-%d"), float(at)))
        if rows:
            store.add_events(user.email, rows)
        return {"ok": True, "n": len(rows)}

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
        if stop := paused():
            return stop
        feature, t0 = feature_of(request), time.monotonic()
        body = await request.json()
        q = str(body.get("query") or "").strip()[:400]
        if not q:
            return _reject("empty query", 400)
        n = max(1, min(int(body.get("max_results") or 6), 10))
        try:
            r = await http.post(TAVILY_URL, json={"api_key": tavily_key, "query": q, "max_results": n})
        except httpx.HTTPError:
            failed(user.email, "search:tavily", 502, {"error": {"type": "network"}}, feature)
            return _reject("search upstream unreachable", 502)
        if r.status_code >= 400:
            failed(user.email, "search:tavily", r.status_code, None, feature)
            return _reject(f"search upstream {r.status_code}", 502)
        charge(user.email, "search:tavily", 0, 0, search_price_usd, feature, t0)
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
        if stop := paused():
            return stop
        feature, t0 = feature_of(request), time.monotonic()
        body = await request.json()
        model = body.get("model") or ""
        if model not in prices:
            return _reject(f"model not allowed: {model}", 400)
        stream = bool(body.get("stream"))
        if stream:                                   # 没有 usage 就没法记账：强制要
            body["stream_options"] = {"include_usage": True}
        headers = {"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"}

        if not stream:
            try:
                r = await http.post(OPENAI_URL, json=body, headers=headers)
            except httpx.HTTPError:
                failed(user.email, model, 502, {"error": {"type": "network"}}, feature)
                return _reject("upstream unreachable", 502, "upstream")
            out = r.json()
            if r.status_code >= 400:
                failed(user.email, model, r.status_code, out, feature)
            u = out.get("usage") or {}
            if r.status_code < 400:
                pt, ct = u.get("prompt_tokens") or 0, u.get("completion_tokens") or 0
                charge(user.email, model, pt, ct, cost_usd(prices, model, pt, ct), feature, t0)
            return JSONResponse(out, status_code=r.status_code)

        req = http.build_request("POST", OPENAI_URL, json=body, headers=headers)
        try:
            upstream = await http.send(req, stream=True)
        except httpx.HTTPError:
            failed(user.email, model, 502, {"error": {"type": "network"}}, feature)
            return _reject("upstream unreachable", 502, "upstream")
        if upstream.status_code >= 400:
            text = await upstream.aread()
            await upstream.aclose()
            failed(user.email, model, upstream.status_code, text, feature)
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
                    charge(user.email, model, pt, ct, cost_usd(prices, model, pt, ct), feature, t0)

        return StreamingResponse(relay(), status_code=upstream.status_code,
                                 media_type="text/event-stream")

    return app
