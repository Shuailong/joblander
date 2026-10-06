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
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Query, Request
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
       "x-joblander-gateway", "x-joblander-set-lang"}


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
    feedback_to: str = ""                            # 反馈收件人（管理员邮箱）
    resend_api_key: str = ""
    feedback_from: str = "joblander <onboarding@resend.dev>"
    low_balance_usd: float = 0.5  # 额度提醒线（后台标红也用它）
    mail_from: str = ""          # 已验证域名的发件人，如 "joblander <hello@ailayoff.me>"；空 = 不给用户发信


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

    log = logging.getLogger("uvicorn.error")

    @app.middleware("http")
    async def redacted_access_log(request: Request, call_next):
        """访问日志只记方法、路由大类、状态码、IP——URL 里可能有公司名与文档名，不进日志。"""
        t0 = time.time()
        resp = await call_next(request)
        p = request.url.path
        kind = next((k for k in ("/_gw/static", "/_gw/", "/auth/", "/api/", "/static/") if p.startswith(k)), "page")
        ip = request.client.host if request.client else "-"
        log.info("%s %s %s %dms %s", request.method, kind, resp.status_code, (time.time() - t0) * 1000, ip)
        return resp

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
        lg = "en" if to == "en" else "zh"
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie("jl_lang", lg, max_age=365 * 86400, samesite="lax")
        # 主动切换 = 明确选择：登录后的第一个请求把它写进引擎配置，盖过之前自动检测记下的语言
        resp.set_cookie("jl_lang_set", lg, max_age=86400, samesite="lax")
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

    async def delete(email: str) -> None:
        """彻底删除：先销毁 machine 与卷，成功后再删网关里关于此人的全部记录。"""
        user = store.get(email)
        try:
            if user.machine_id:
                await fly.destroy_machine(user.machine_id)
            if user.volume_id:
                await fly.delete_volume(user.volume_id)
            store.delete_user(email)
        except Exception as e:                                  # noqa: BLE001  删不干净就别删记录，留着重试
            store.set_status(email, "failed", error=f"delete: {e}"[:500])
        finally:
            provisioning.pop(email, None)

    app.state.delete = delete

    def needs_consent(user: User) -> bool:
        return user.privacy_version != pages.PRIVACY_VERSION

    def same_origin(request: Request) -> bool:
        origin = request.headers.get("origin") or ""
        return not origin or origin == f"https://{settings.public_host}"

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
            if store.record_blocked(email, lg):
                try:
                    from gw.notify import send_blocked
                    await send_blocked(google, settings.resend_api_key, settings.feedback_to,
                                       sender=settings.feedback_from, user=email, lang=lg)
                    from gw.notify import send_user
                    await send_user(google, settings.resend_api_key, settings.mail_from, settings.feedback_to,
                                    to=email, kind="waitlisted", lang=lg)
                except Exception:                               # noqa: BLE001  通知失败不影响提示页
                    pass
            t = pages.msg("beta", lg)
            return _page(t, f"<h1>{t}</h1><p>{pages.msg('not_invited_mail' if settings.mail_from else 'not_invited', lg,
                                                                email=html.escape(email))}</p>",
                         lang=lg)
        if not store.get(email):
            store.create(email, settings.free_credit_usd)
        store.set_lang(email, lang(request))
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
        if needs_consent(user):
            return {"status": "consent", "stage": 0}
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

    @app.post("/_gw/feedback")
    async def feedback(request: Request):
        """应用内反馈：先存库（不丢），再尽力发邮件给管理员；每人每小时最多 10 条。"""
        email = current(request)
        if not email or store.get(email) is None:
            return Response(status_code=401)
        origin = request.headers.get("origin") or ""
        if origin and origin != f"https://{settings.public_host}":
            return Response(status_code=403)
        form = await request.form()
        message = str(form.get("message") or "").strip()[:5000]
        if len(message) < 3:
            return {"error": "empty"}
        if store.feedback_count_since(email, time.time() - 3600) >= 10:
            return {"error": "rate"}
        page = str(form.get("page") or "")[:300]
        lg = str(form.get("lang") or lang(request))[:5]
        ua = (request.headers.get("user-agent") or "")[:300]
        fid = store.add_feedback(email, message, page, lg, ua)
        try:
            from gw.notify import send_feedback
            if await send_feedback(google, settings.resend_api_key, settings.feedback_to,
                                   sender=settings.feedback_from, user=email, message=message,
                                   page=page, lang=lg, ua=ua, fid=fid):
                store.mark_feedback_emailed(fid)
        except Exception:                                       # noqa: BLE001  邮件失败不影响收下反馈
            pass
        return {"ok": True}

    @app.get("/_gw/privacy")
    async def privacy_page(request: Request, lang_q: str = Query("", alias="lang")):
        return pages.privacy(lang_q if lang_q in ("zh", "en") else lang(request))

    @app.post("/_gw/consent")
    async def give_consent(request: Request):
        email = current(request)
        if not email or store.get(email) is None:
            return Response(status_code=401)
        if not same_origin(request):
            return Response(status_code=403)
        store.consent(email, pages.PRIVACY_VERSION)
        return RedirectResponse("/", status_code=303)

    @app.get("/_gw/export")
    async def export(request: Request):
        """网关侧记录（账户、额度、用量、反馈）；空间里的文件由引擎 /api/export 打包。"""
        email = current(request)
        if not email or store.get(email) is None:
            return Response(status_code=401)
        body = json.dumps(store.export(email), ensure_ascii=False, indent=1)
        return Response(body, media_type="application/json", headers={
            "content-disposition": 'attachment; filename="joblander-account.json"'})

    @app.post("/_gw/delete")
    async def delete_account(request: Request):
        email = current(request)
        user = store.get(email) if email else None
        if user is None:
            return Response(status_code=401)
        if not same_origin(request):
            return Response(status_code=403)
        form = await request.form()
        if (form.get("confirm") or "").strip() != "DELETE":
            return {"error": "confirm"}
        if email in provisioning:
            return {"error": "busy"}
        store.set_status(email, "deleting")
        provisioning[email] = asyncio.create_task(delete(email))
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

    @app.get("/_gw/me")
    async def me(request: Request):
        """应用侧栏的账户菜单与设置页「账户」一节用：同源直接问网关，不经用户 machine。"""
        email = current(request)
        user = store.get(email) if email else None
        if user is None:
            return Response(status_code=401)
        bal = max(user.balance_usd, 0)
        return {"email": user.email, "admin": user.email in settings.admins,
                "balance_usd": round(bal, 4), "credit_usd": round(user.credit_usd, 4),
                "spent_usd": round(user.spent_usd, 4), "low": bal < settings.low_balance_usd}

    @app.get("/_gw/account")
    async def account(request: Request):
        """用量明细：近 30 天按天汇总。账户本身（邮箱、退出、额度概览）在应用的设置页。"""
        email = current(request)
        user = store.get(email) if email else None
        if user is None:
            return RedirectResponse("/auth/login", status_code=302)
        tz = ZoneInfo(settings.timezone)
        days: dict[str, list] = {}
        for u in store.usage_since(user.email, time.time() - 30 * 86400):
            d = days.setdefault(datetime.fromtimestamp(u["at"], tz).strftime("%Y-%m-%d"), [0, 0.0])
            d[0] += 1
            d[1] += u["cost_usd"]
        return pages.usage_page(email=user.email, balance=max(user.balance_usd, 0), credit=user.credit_usd,
                                spent=user.spent_usd, days=[(k, n, c) for k, (n, c) in days.items()],
                                lang=lang(request))

    # ---------- 管理后台（只给管理员；别人一律 404，不暴露它存在） ----------

    def admin_of(request: Request) -> str | None:
        email = current(request)
        return email if email and email in settings.admins else None

    def back(msg: str) -> RedirectResponse:
        return RedirectResponse("/_gw/admin?" + urlencode({"m": msg}), status_code=303)

    @app.get("/_gw/admin")
    async def admin_page(request: Request, m: str = ""):
        if not admin_of(request):
            return Response(status_code=404)
        from gw import admin
        snap = store.admin_snapshot(time.time() - admin.DAYS * 86400)
        return admin.render(snap, low_usd=settings.low_balance_usd, tz_name=settings.timezone,
                            privacy_version=pages.PRIVACY_VERSION, flash=m[:200])

    async def admin_form(request: Request) -> tuple[str, dict] | None:
        email = admin_of(request)
        if not email or not same_origin(request):
            return None
        return email, await request.form()

    @app.post("/_gw/admin/invite")
    async def admin_invite(request: Request):
        got = await admin_form(request)
        if got is None:
            return Response(status_code=404)
        target = str(got[1].get("email") or "").strip().lower()
        if "@" not in target or len(target) > 254:
            return back("邮箱不对")
        lg = store.blocked_lang(target)
        store.invite(target)
        mailed = False
        try:
            from gw.notify import send_user
            mailed = await send_user(google, settings.resend_api_key, settings.mail_from, settings.feedback_to,
                                     to=target, kind="invited", lang=lg)
        except Exception:                                       # noqa: BLE001
            pass
        return back(f"已邀请 {target}" + ("，已发邮件通知" if mailed else "（没发出邮件，记得自己告诉对方）"))

    @app.post("/_gw/admin/dismiss")
    async def admin_dismiss(request: Request):
        got = await admin_form(request)
        if got is None:
            return Response(status_code=404)
        target = str(got[1].get("email") or "").strip().lower()
        return back(f"已清掉 {target}" if store.dismiss(target) else f"{target} 不在被拦名单")

    @app.post("/_gw/admin/grant")
    async def admin_grant(request: Request):
        got = await admin_form(request)
        if got is None:
            return Response(status_code=404)
        admin_email, form = got
        target = str(form.get("email") or "").strip().lower()
        try:
            usd = float(form.get("usd") or 0)
        except ValueError:
            usd = 0
        if not (0 < usd <= 100) or store.get(target) is None:
            return back("没加：金额须在 0–100 之间，且对方已登录过")
        store.grant(target, usd, f"后台手工发放（{admin_email}）")
        return back(f"已给 {target} 加 ${usd:g}，余额 ${store.get(target).balance_usd:.2f}")

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
        if needs_consent(user):                                 # 先看隐私说明并同意，才开通 / 继续使用
            if request.method != "GET" or path.startswith("api/"):
                return Response(status_code=403)
            return pages.consent(lang(request))
        if user.status == "deleting":
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
        chosen = request.cookies.get("jl_lang_set")
        if chosen in ("zh", "en"):
            headers["x-joblander-set-lang"] = chosen
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

        out = StreamingResponse(body(), status_code=resp.status_code, headers=out_headers)
        if chosen in ("zh", "en") and resp.status_code < 400:
            out.delete_cookie("jl_lang_set")                    # 已送达引擎，只生效一次
        return out

    return app


def load_json_env(raw: str) -> dict:
    return json.loads(raw) if raw else {}
