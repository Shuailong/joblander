"""公网入口：Google 登录 → 邀请名单 → 首次登录开 machine → 之后所有请求转发到这个人自己的 machine。

浏览器只认识 app.ailayoff.me 一个域名；用户 machine 在私网里，公网打不到。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse

from gw import pages
from gw.flyapi import Fly
from gw.store import Store, User

SESSION_COOKIE = "jl_session"
SESSION_TTL = 30 * 86400
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
# 逐跳头不转发；cookie 是网关自己的登录态，不给用户 machine
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
       "trailer", "transfer-encoding", "upgrade", "host", "cookie", "content-length",
       "x-joblander-gateway"}


@dataclass
class Settings:
    public_host: str                    # app.ailayoff.me
    session_secret: str
    google_client_id: str
    google_client_secret: str
    user_image: str                     # registry.fly.io/joblander-users:vN
    meter_url: str                      # http://joblander-gw.internal:8081/v1
    free_credit_usd: float = 2.0
    memory_mb: int = 1024        # chromium 转 PDF 在 512MB 下卡死
    timezone: str = "Asia/Singapore"
    admins: set[str] = field(default_factory=set)   # 管理员免邀请


# ---------- 会话：HMAC 签名的 email|过期时间，不存服务端 ----------

def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session(secret: str, email: str, now: float | None = None) -> str:
    payload = f"{email}|{int((now or time.time()) + SESSION_TTL)}"
    raw = f"{payload}|{_sign(secret, payload)}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def read_session(secret: str, cookie: str | None, now: float | None = None) -> str | None:
    if not cookie:
        return None
    try:
        email, exp, sig = base64.urlsafe_b64decode(cookie.encode()).decode().rsplit("|", 2)
    except Exception:
        return None
    if not hmac.compare_digest(sig, _sign(secret, f"{email}|{exp}")):
        return None
    if int(exp) < (now or time.time()):
        return None
    return email


def _page(title: str, body: str, refresh: int = 0, lang: str = "zh") -> HTMLResponse:
    return pages.simple(title, body, refresh, lang=lang)


def create_web_app(settings: Settings, store: Store, fly: Fly,
                   upstream: httpx.AsyncClient | None = None) -> FastAPI:
    app = FastAPI(title="joblander-gateway", docs_url=None, redoc_url=None, openapi_url=None)
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles
    app.mount("/_gw/static", StaticFiles(directory=Path(__file__).parent / "static"), name="gwstatic")
    http = upstream or httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10))
    google = httpx.AsyncClient(timeout=20)
    provisioning: dict[str, asyncio.Task] = {}
    redirect_uri = f"https://{settings.public_host}/auth/callback"

    def current(request: Request) -> str | None:
        return read_session(settings.session_secret, request.cookies.get(SESSION_COOKIE))

    def lang(request: Request) -> str:
        return pages.lang_of(request.cookies.get("jl_lang"), request.headers.get("accept-language"))

    def failed(request: Request, key: str, retry: bool = True) -> HTMLResponse:
        lg = lang(request)
        t = pages.msg("login_failed", lg)
        btn = f'<a class="btn" href="/auth/login">{pages.msg("relogin", lg)}</a>' if retry else ""
        return _page(t, f"<h1>{t}</h1><p>{pages.msg(key, lg)}</p>{btn}", lang=lg)

    @app.get("/_gw/lang")
    async def switch_lang(to: str = "zh"):
        """未登录首页的中 / 英切换；登录后界面语言在引擎的设置页里改。"""
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie("jl_lang", "en" if to == "en" else "zh", max_age=365 * 86400, samesite="lax")
        return resp

    async def provision(email: str, meter_key: str) -> None:
        """开卷 + 开 machine。失败记在 users.error，用户刷新页面可重试。"""
        user = store.get(email)
        try:
            store.set_status(email, "provisioning")
            volume_id = user.volume_id or await fly.create_volume()
            store.set_status(email, "provisioning", volume_id=volume_id)
            env = {"JOBLANDER_GATEWAY_TOKEN": user.gateway_token,
                   "JOBLANDER_ALLOWED_HOSTS": settings.public_host,
                   "OPENAI_API_KEY": meter_key,
                   "OPENAI_BASE_URL": settings.meter_url,
                   "JOBLANDER_SEARCH_URL": settings.meter_url.rstrip("/") + "/search",
                   "JOBLANDER_TZ": settings.timezone}
            name = "u-" + hashlib.sha256(email.encode()).hexdigest()[:12]
            mid = await fly.create_machine(
                name, fly.machine_config(settings.user_image, env, volume_id, settings.memory_mb))
            store.set_status(email, "provisioning", machine_id=mid)
            await fly.wait_started(mid)
            store.set_status(email, "ready")
        except Exception as e:                                  # noqa: BLE001
            store.set_status(email, "failed", error=str(e)[:500])
        finally:
            provisioning.pop(email, None)

    async def reset(email: str) -> None:
        """一键重置：销毁 machine 与卷（数据不可恢复），账号回到新用户状态。"""
        user = store.get(email)
        try:
            if user.machine_id:
                await fly.destroy_machine(user.machine_id)
            if user.volume_id:
                await fly.delete_volume(user.volume_id)
            store.clear_machine(email)
        except Exception as e:                                  # noqa: BLE001
            store.set_status(email, "failed", error=f"reset: {e}"[:500])
        finally:
            provisioning.pop(email, None)

    app.state.reset = reset                                      # 管理命令复用同一条路径

    def kick_provision(user: User) -> None:
        if user.email in provisioning:
            return
        # 重试时子 key 明文已不可得（只存哈希）：轮换一把新的
        meter_key = store.rotate_meter_key(user.email)
        provisioning[user.email] = asyncio.create_task(provision(user.email, meter_key))

    # ---------- 登录 ----------

    @app.get("/auth/login")
    async def login():
        state = secrets.token_urlsafe(16)
        url = GOOGLE_AUTH + "?" + urlencode({
            "client_id": settings.google_client_id, "redirect_uri": redirect_uri,
            "response_type": "code", "scope": "openid email", "state": state,
            "prompt": "select_account"})
        resp = RedirectResponse(url, status_code=302)
        resp.set_cookie("jl_state", state, max_age=600, httponly=True, secure=True, samesite="lax")
        return resp

    @app.get("/auth/callback")
    async def callback(request: Request, code: str = "", state: str = ""):
        if not state or not hmac.compare_digest(state, request.cookies.get("jl_state") or ""):
            return failed(request, "state_expired")
        tok = await google.post(GOOGLE_TOKEN, data={
            "code": code, "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret, "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"})
        if tok.status_code != 200:
            return failed(request, "google_refused")
        info = (await google.get(GOOGLE_USERINFO, headers={
            "Authorization": f"Bearer {tok.json()['access_token']}"})).json()
        email = (info.get("email") or "").lower()
        if not email or not info.get("email_verified"):
            return failed(request, "unverified", retry=False)
        if email not in settings.admins and not store.is_invited(email) and not store.get(email):
            lg = lang(request)
            t = pages.msg("beta", lg)
            return _page(t, f"<h1>{t}</h1><p>{pages.msg('not_invited', lg, email=html.escape(email))}</p>",
                         lang=lg)
        if not store.get(email):
            store.create(email, settings.free_credit_usd)
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie(SESSION_COOKIE, make_session(settings.session_secret, email),
                        max_age=SESSION_TTL, httponly=True, secure=True, samesite="lax")
        resp.delete_cookie("jl_state")
        return resp

    @app.get("/auth/logout")
    async def logout():
        resp = RedirectResponse("/", status_code=302)
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    @app.get("/_gw/status")
    async def status(request: Request):
        """等待页轮询：真实开通进度（0 分配存储 → 1 启动 → 2 热身 → 3 就绪）。"""
        email = current(request)
        user = store.get(email) if email else None
        if user is None:
            return Response(status_code=401)
        if user.status in ("new", "failed") and email not in provisioning:
            kick_provision(user)
        stage = (3 if user.status == "ready" else 0 if user.status == "resetting"
                 else 2 if user.machine_id else 1 if user.volume_id else 0)
        return {"status": user.status, "stage": stage}

    @app.post("/_gw/reset")
    async def reset_account(request: Request):
        email = current(request)
        user = store.get(email) if email else None
        if user is None:
            return Response(status_code=401)
        # 写操作：浏览器跨站提交一定带 Origin，必须是本站；再要一次手打确认
        origin = request.headers.get("origin") or ""
        if origin and origin != f"https://{settings.public_host}":
            return Response(status_code=403)
        form = await request.form()
        if (form.get("confirm") or "").strip() != "RESET":
            return {"error": "confirm"}
        if email in provisioning:
            return {"error": "busy"}
        store.set_status(email, "resetting")
        provisioning[email] = asyncio.create_task(reset(email))
        return {"ok": True}

    @app.get("/_gw/balance")
    async def balance(request: Request):
        """侧栏额度显示：浏览器同源直接问网关，不经用户 machine。"""
        email = current(request)
        user = store.get(email) if email else None
        if user is None:
            return Response(status_code=401)
        return {"balance_usd": round(max(user.balance_usd, 0), 4),
                "credit_usd": round(user.credit_usd, 4), "spent_usd": round(user.spent_usd, 4)}

    @app.get("/_gw/account")
    async def account(request: Request):
        email = current(request)
        user = store.get(email) if email else None
        if user is None:
            return RedirectResponse("/auth/login", status_code=302)
        rows = "".join(
            f"<tr><td>{time.strftime('%m-%d %H:%M', time.localtime(u['at']))}</td>"
            f"<td>{html.escape(u['model'])}</td><td style='text-align:right'>${u['cost_usd']:.4f}</td></tr>"
            for u in store.recent_usage(user.email))
        lg = lang(request)
        t = pages.msg("account", lg)
        bal = pages.msg("balance", lg, bal=f"{max(user.balance_usd, 0):.2f}",
                        credit=f"{user.credit_usd:.2f}", spent=f"{user.spent_usd:.2f}")
        empty = f"<tr><td>{pages.msg('no_usage', lg)}</td></tr>"
        return _page(t, f"<h1>{t}</h1><p>{html.escape(user.email)}</p><p>{bal}</p>"
                     f"<table>{rows or empty}</table>"
                     f'<p style="margin-top:16px"><a href="/">{pages.msg("back", lg)}</a> · '
                     f'<a href="/auth/logout">{pages.msg("logout", lg)}</a></p>', lang=lg)

    # ---------- 其余一切：转发到这个人自己的 machine ----------

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def proxy(request: Request, path: str):
        email = current(request)
        if not email:
            if request.method != "GET" or path.startswith("api/"):
                return Response(status_code=401)
            return pages.landing(lang(request))
        user = store.get(email)
        if user is None:                                        # 会话在、人被删了
            return RedirectResponse("/auth/logout", status_code=302)
        if user.status != "ready":
            if user.status in ("new", "failed") and email not in provisioning:
                kick_provision(user)
            if request.method != "GET" or path.startswith("api/"):
                return Response(status_code=503)
            return pages.waiting(first_time=not user.machine_id or user.status == "resetting",
                                 lang=lang(request))

        url = f"http://{fly.address(user.machine_id)}:8899/{path}"
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
        headers["host"] = settings.public_host
        if request.cookies.get("jl_lang") in ("zh", "en"):   # 首页选过的语言带进引擎（设置里改的仍优先）
            headers["accept-language"] = request.cookies["jl_lang"]
        headers["x-joblander-gateway"] = user.gateway_token
        req = http.build_request(request.method, url, params=request.query_params,
                                 headers=headers, content=request.stream())
        try:
            resp = await http.send(req, stream=True)
        except httpx.HTTPError:
            lg = lang(request)
            return _page(pages.msg("unreachable_t", lg), pages.msg("unreachable", lg), refresh=5, lang=lg)
        out_headers = {k: v for k, v in resp.headers.items()
                       if k.lower() not in HOP and k.lower() != "content-encoding"}

        async def body():
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk
            finally:
                await resp.aclose()

        return StreamingResponse(body(), status_code=resp.status_code, headers=out_headers)

    return app


def load_json_env(raw: str) -> dict:
    return json.loads(raw) if raw else {}
