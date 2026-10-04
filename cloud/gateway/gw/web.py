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


def _page(title: str, body: str, refresh: int = 0) -> HTMLResponse:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return HTMLResponse(f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{meta}<title>{title}</title>
<style>
:root{{--bg:#F7F7F5;--surface:#fff;--ink:#26251E;--ink-2:#6F6D64;--accent:#0E6E62;--line:#E8E6E1}}
@media (prefers-color-scheme: dark){{:root{{--bg:#191A18;--surface:#20221F;--ink:#E9E8E3;--ink-2:#A5A49B;--accent:#3FA294;--line:#31332E}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,"PingFang SC","Noto Sans SC",sans-serif}}
.box{{max-width:440px;margin:12vh auto;padding:28px 24px;background:var(--surface);border:1px solid var(--line);border-radius:12px}}
h1{{font-size:20px;margin:0 0 8px}} p{{color:var(--ink-2);margin:0 0 16px}}
a.btn{{display:inline-block;background:var(--accent);color:#fff;padding:8px 16px;border-radius:8px;text-decoration:none;font-weight:600}}
table{{width:100%;border-collapse:collapse;font-size:13px}} td{{padding:4px 0;border-bottom:1px solid var(--line)}}
@media (max-width:480px){{.box{{margin:16px;}}}}
</style></head><body><div class="box">{body}</div></body></html>""")


def create_web_app(settings: Settings, store: Store, fly: Fly,
                   upstream: httpx.AsyncClient | None = None) -> FastAPI:
    app = FastAPI(title="joblander-gateway", docs_url=None, redoc_url=None, openapi_url=None)
    http = upstream or httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10))
    google = httpx.AsyncClient(timeout=20)
    provisioning: dict[str, asyncio.Task] = {}
    redirect_uri = f"https://{settings.public_host}/auth/callback"

    def current(request: Request) -> str | None:
        return read_session(settings.session_secret, request.cookies.get(SESSION_COOKIE))

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
            return _page("登录失败", "<h1>登录失败</h1><p>登录状态过期，请重试。</p>"
                         '<a class="btn" href="/auth/login">重新登录</a>')
        tok = await google.post(GOOGLE_TOKEN, data={
            "code": code, "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret, "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"})
        if tok.status_code != 200:
            return _page("登录失败", "<h1>登录失败</h1><p>Google 没有确认这次登录，请重试。</p>"
                         '<a class="btn" href="/auth/login">重新登录</a>')
        info = (await google.get(GOOGLE_USERINFO, headers={
            "Authorization": f"Bearer {tok.json()['access_token']}"})).json()
        email = (info.get("email") or "").lower()
        if not email or not info.get("email_verified"):
            return _page("登录失败", "<h1>登录失败</h1><p>这个 Google 账号的邮箱未验证。</p>")
        if email not in settings.admins and not store.is_invited(email) and not store.get(email):
            return _page("还在内测", f"<h1>还在内测</h1><p>{html.escape(email)} 还不在邀请名单里。"
                         "找把你拉进来的朋友加一下，再回来登录。</p>")
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
        return _page("账户", f"<h1>账户</h1><p>{html.escape(user.email)}</p>"
                     f"<p>AI 额度余额：<b>${max(user.balance_usd, 0):.2f}</b>"
                     f"（累计 ${user.credit_usd:.2f}，已用 ${user.spent_usd:.2f}）</p>"
                     f"<table>{rows or '<tr><td>还没有用量</td></tr>'}</table>"
                     '<p style="margin-top:16px"><a href="/">← 返回</a> · <a href="/auth/logout">退出登录</a></p>')

    # ---------- 其余一切：转发到这个人自己的 machine ----------

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def proxy(request: Request, path: str):
        email = current(request)
        if not email:
            if request.method != "GET" or path.startswith("api/"):
                return Response(status_code=401)
            return _page("joblander", "<h1>joblander</h1><p>求职作战系统的云端版。"
                         "登录后会为你开一个独立的空间，数据只在你自己的空间里。</p>"
                         '<a class="btn" href="/auth/login">用 Google 登录</a>')
        user = store.get(email)
        if user is None:                                        # 会话在、人被删了
            return RedirectResponse("/auth/logout", status_code=302)
        if user.status != "ready":
            if user.status in ("new", "failed") and email not in provisioning:
                kick_provision(user)
            msg = ("上次准备失败了，正在重试。" if user.status == "failed"
                   else "第一次登录，正在为你准备独立空间，大约一分钟。")
            return _page("准备中", f"<h1>马上就好</h1><p>{msg}页面会自动刷新。</p>", refresh=5)

        url = f"http://{fly.address(user.machine_id)}:8899/{path}"
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
        headers["host"] = settings.public_host
        headers["x-joblander-gateway"] = user.gateway_token
        req = http.build_request(request.method, url, params=request.query_params,
                                 headers=headers, content=request.stream())
        try:
            resp = await http.send(req, stream=True)
        except httpx.HTTPError:
            return _page("暂时连不上", "<h1>你的空间暂时没响应</h1>"
                         "<p>可能正在重启，几秒后自动重试。</p>", refresh=5)
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
