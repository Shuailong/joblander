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
    idle_minutes: int = 0        # 用户 machine 闲置多久就挂起；0 = 不休眠（常开）
    wake_at: str = "02:35,08:20,21:35,sun 20:05"   # 定时叫醒（引擎夜扫 / 晨报 / 日记 / 周报之后）
    digest_at: str = "09:00"     # 每天几点给管理员发汇总邮件（新申请 / 额度申请 / 反馈）；空 = 不发
    geoip_db: str = "/app/geo.mmdb"   # 离线 IP 库（镜像构建时下载）；不在就只记 IP
    mail_gap_s: float = 0.6      # 给用户发信时每封之间的间隔（Resend 默认每秒 2 封）
    mail_daily_limit: int = 90   # 最近 24 小时最多给用户发几封（Resend 免费档每天 100，留几封给汇总与告警）；超了就等
    mail_idle_s: float = 3       # 队列空着时多久看一次


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
    from gw.sleep import Sleeper
    sleeper = Sleeper(store, fly, http, idle_minutes=settings.idle_minutes, wake_at=settings.wake_at,
                      tz=settings.timezone, public_host=settings.public_host)
    app.state.sleeper = sleeper

    async def start_sleeper():
        if settings.idle_minutes:
            app.state.sleeper_task = asyncio.create_task(sleeper.run())
    app.router.on_startup.append(start_sleeper)

    from gw.geo import Geo, client_ip
    geo = Geo(settings.geoip_db)

    def note_geo(email: str, request: Request) -> None:
        ip = client_ip(request)
        if ip:
            store.set_geo(email, ip, geo.lookup(ip))

    # ---------- 发信：给用户的信排队慢慢发；给管理员的每天汇总一封 ----------

    mail_task: list[asyncio.Task] = []
    mail_hold = {"until": 0.0}                  # Resend 说额度用完了：到这个时间之前不再试
    mail_wake: list[asyncio.Event] = []         # 有新信入队就叫醒（余额提醒从计量口入队，靠定时看）

    async def mail_nap(seconds: float) -> None:
        try:
            await asyncio.wait_for(mail_wake[0].wait(), seconds)
        except asyncio.TimeoutError:
            pass
        mail_wake[0].clear()

    async def mail_worker() -> None:
        """一直跑：从库里的队列按顺序取信，间隔 mail_gap_s 发；最近 24 小时发满 mail_daily_limit 就等到腾出名额。
        429 不算失败：限流就稍等，当日额度用完就停一小时；其他失败重试，满 5 次放弃。"""
        from gw.notify import post_user
        mail_wake[:] = [asyncio.Event()]
        last_prune = 0.0
        while True:
            now = time.time()
            if now - last_prune > 3600:
                store.prune_mail(now - 7 * 86400)
                last_prune = now
            m = store.next_mail() if now >= mail_hold["until"] else None
            if m is None or store.mail_stats(now - 86400)["sent"] >= settings.mail_daily_limit:
                await mail_nap(settings.mail_idle_s if m is None else 60)
                continue
            try:
                r = await post_user(google, settings.resend_api_key, settings.mail_from, settings.feedback_to,
                                    to=m["to_email"], kind=m["kind"], lang=m["lang"], **m["ctx"])
                if r.status_code < 300:
                    store.mail_done(m["id"])
                    if m["kind"] in ("invited", "invite_reminder"):
                        store.mark_invite_mailed(m["to_email"])
                elif r.status_code == 429:
                    quota = "quota" in r.text
                    mail_hold["until"] = time.time() + (3600 if quota else 5)
                    if quota:
                        log.warning("Resend 当日额度用完，发信队列停一小时（还剩 %d 封）", store.mail_stats(0)["pending"])
                else:
                    store.mail_retry(m["id"], f"{r.status_code} {r.text[:200]}")
            except Exception as e:                              # noqa: BLE001  网络问题：记一次失败，稍后重试
                store.mail_retry(m["id"], repr(e))
            await asyncio.sleep(settings.mail_gap_s)

    def mail_on() -> bool:
        return bool(settings.resend_api_key and settings.mail_from)

    def ensure_mail_worker() -> None:
        if mail_on() and (not mail_task or mail_task[0].done()):
            mail_task[:] = [asyncio.create_task(mail_worker())]

    def queue_mail(to: str, kind: str, lang: str | None, **ctx) -> bool:
        """排进库里的发信队列；没配发件域名返回 False（不排）。"""
        if not mail_on():
            return False
        store.enqueue_mail(to, kind, lang, ctx)
        ensure_mail_worker()
        if mail_wake:
            mail_wake[0].set()
        return True

    async def start_mail():                     # 重启后接着发上次没发完的
        ensure_mail_worker()
    app.router.on_startup.append(start_mail)

    async def send_digest(now: float | None = None) -> bool | None:
        """把上次汇总以来的新申请 / 额度申请 / 反馈发给管理员；发出才往前推进时间点（失败下次再带上）。"""
        from gw.notify import send_digest as _send
        now = now or time.time()
        since = float(store.get_kv("digest_at") or now - 86400)
        d = store.digest_since(since)
        ok = await _send(google, settings.resend_api_key, settings.feedback_to, sender=settings.feedback_from, d=d,
                         day=datetime.fromtimestamp(now, ZoneInfo(settings.timezone)).strftime("%Y-%m-%d"))
        if ok is not False:
            store.set_kv("digest_at", str(now))
            for f in d["feedback"] if ok else []:
                store.mark_feedback_emailed(f["id"])
        return ok

    app.state.send_digest = send_digest

    async def digest_loop() -> None:
        tz = ZoneInfo(settings.timezone)
        hh, mm = (int(x) for x in settings.digest_at.split(":"))
        while True:
            now = datetime.now(tz)
            if (now.hour, now.minute) >= (hh, mm) and store.get_kv("digest_day") != now.strftime("%Y-%m-%d"):
                try:
                    if await send_digest() is not False:
                        store.set_kv("digest_day", now.strftime("%Y-%m-%d"))
                except Exception:                               # noqa: BLE001
                    log.exception("每日汇总发送失败")
            await asyncio.sleep(300)

    async def start_digest():
        if settings.digest_at and settings.resend_api_key and settings.feedback_to:
            app.state.digest_task = asyncio.create_task(digest_loop())
    app.router.on_startup.append(start_digest)
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
            store.record_blocked(email, lg)                     # 不当场发信：每天汇总一封给管理员
            note_geo(email, request)
            t = pages.msg("beta", lg)
            return _page(t, f"<h1>{t}</h1><p>{pages.msg('not_invited_mail' if settings.mail_from else 'not_invited', lg,
                                                                email=html.escape(email))}</p>",
                         lang=lg)
        if not store.get(email):
            store.create(email, settings.free_credit_usd)
        store.set_lang(email, lang(request))
        note_geo(email, request)
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
        store.add_feedback(email, message, page, lg, ua)        # 邮件进每日汇总
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
                "spent_usd": round(user.spent_usd, 4), "low": bal < settings.low_balance_usd,
                "request": store.latest_request(user.email)}

    @app.post("/_gw/credit-request")
    async def credit_request(request: Request):
        """应用里「申请更多额度」：写几句用途 / 反馈，存库（管理员在每日汇总里看到）；同一时间只能有一条待批。"""
        email = current(request)
        user = store.get(email) if email else None
        if user is None:
            return Response(status_code=401)
        if not same_origin(request):
            return Response(status_code=403)
        form = await request.form()
        message = str(form.get("message") or "").strip()[:3000]
        if len(message) < 10:
            return {"error": "short"}
        rid = store.request_credit(email, message)
        if rid is None:
            return {"error": "pending"}
        return {"ok": True, "request": store.latest_request(email)}

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

    from gw.admin import RET_KEYS, mask

    def back(msg: str, form=None, anchor: str = "") -> RedirectResponse:
        """操作完回后台：带回原来的分页 / 搜索（表单里的 ret），并跳到对应卡片。"""
        from urllib.parse import parse_qsl
        ret = {k: v for k, v in parse_qsl(str(form.get("ret") or "") if form else "")
               if k in RET_KEYS and len(v) <= 100}
        return RedirectResponse("/_gw/admin?" + urlencode({**ret, "m": msg}) + (f"#{anchor}" if anchor else ""),
                                status_code=303)

    @app.get("/_gw/admin")
    async def admin_page(request: Request, m: str = ""):
        if not admin_of(request):
            return Response(status_code=404)
        from gw import admin
        snap = store.admin_snapshot(time.time() - admin.DAYS * 86400)
        return admin.render(snap, low_usd=settings.low_balance_usd, tz_name=settings.timezone,
                            asleep=sleeper.asleep if settings.idle_minutes else None,
                            privacy_version=pages.PRIVACY_VERSION, flash=m[:200],
                            params={k: v for k, v in request.query_params.items() if k in RET_KEYS},
                            mail=({**store.mail_stats(time.time() - 86400), "limit": settings.mail_daily_limit}
                                  if mail_on() else None))

    async def admin_form(request: Request) -> tuple[str, dict] | None:
        email = admin_of(request)
        if not email or not same_origin(request):
            return None
        return email, await request.form()

    def invite_and_mail(target: str) -> bool:
        lg = store.mail_lang(target)
        store.invite(target)
        return queue_mail(target, "invited", lg)

    def emails_of(vals) -> list[str]:
        out = []
        for v in vals:
            e = str(v).strip().lower()
            if "@" in e and len(e) <= 254 and e not in out:
                out.append(e)
        return out

    @app.post("/_gw/admin/invite")
    async def admin_invite(request: Request):
        got = await admin_form(request)
        if got is None:
            return Response(status_code=404)
        form = got[1]
        target = str(form.get("email") or "").strip().lower()
        if "@" not in target or len(target) > 254:
            return back("邮箱不对", form, "invites")
        mailed = invite_and_mail(target)
        return back(f"已邀请 {mask(target)}" + ("，邮件已排队发送" if mailed else "（没配发信，记得自己告诉对方）"),
                    form, "waitlist")

    @app.post("/_gw/admin/waitlist")
    async def admin_waitlist_batch(request: Request):
        """被拦名单批量操作：勾选的人一起邀请（邮件排队慢慢发）或一起清掉。"""
        got = await admin_form(request)
        if got is None:
            return Response(status_code=404)
        form = got[1]
        # 行内按钮 act="invite:邮箱"；表头按钮 act="invite"，对象是勾选的 sel
        action, _, one = str(form.get("act") or "").partition(":")
        targets = emails_of([one] if one else form.getlist("sel"))
        if not targets:
            return back("没勾选任何人", form, "waitlist")
        if action == "dismiss":
            n = sum(store.dismiss(t) for t in targets)
            return back(f"已清掉 {n} 人", form, "waitlist")
        mailed = sum(invite_and_mail(t) for t in targets)
        return back(f"已邀请 {len(targets)} 人" + (f"，{mailed} 封邀请邮件已排队（每天最多 {settings.mail_daily_limit} 封，多的顺延）"
                                                if mailed else "（没配发信，记得自己告诉对方）") if len(targets) > 1 else
                    f"已邀请 {mask(targets[0])}" + ("，邮件已排队发送" if mailed else "（没配发信，记得自己告诉对方）"),
                    form, "waitlist")

    @app.post("/_gw/admin/resend-invites")
    async def admin_resend_invites(request: Request):
        """邀请了、还没登录、邀请邮件也没发出去的人：重新排队发一遍。"""
        got = await admin_form(request)
        if got is None:
            return Response(status_code=404)
        todo = [i["email"] for i in store.admin_snapshot(time.time())["pending_invites"]
                if not i["mailed_at"] and not store.mail_pending(i["email"], "invited")]      # 还在排队的不重复排
        n = sum(queue_mail(e, "invited", store.mail_lang(e)) for e in todo)
        return back(f"{n} 封邀请邮件已重新排队" if n else "没有要重发的（或没配发信）", got[1], "invites")

    @app.post("/_gw/admin/remind-invites")
    async def admin_remind_invites(request: Request):
        """已邀请、还没登录的人：每人再发一封提醒（已在队列里等着发的跳过）。"""
        got = await admin_form(request)
        if got is None:
            return Response(status_code=404)
        todo = [i["email"] for i in store.admin_snapshot(time.time())["pending_invites"]
                if not store.mail_pending(i["email"], "invited") and not store.mail_pending(i["email"], "invite_reminder")]
        n = sum(queue_mail(e, "invite_reminder", store.mail_lang(e)) for e in todo)
        return back(f"{n} 封提醒已排队（每天最多 {settings.mail_daily_limit} 封，多的顺延）" if n
                    else "没有要提醒的人（或没配发信）", got[1], "invites")

    @app.post("/_gw/admin/dismiss")
    async def admin_dismiss(request: Request):
        got = await admin_form(request)
        if got is None:
            return Response(status_code=404)
        form = got[1]
        target = str(form.get("email") or "").strip().lower()
        return back(f"已清掉 {mask(target)}" if store.dismiss(target) else f"{mask(target)} 不在被拦名单", form, "waitlist")

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
            return back("没加：金额须在 0–100 之间，且对方已登录过", form, "users")
        store.grant(target, usd, f"后台手工发放（{admin_email}）")
        return back(f"已给 {mask(target)} 加 ${usd:g}，余额 ${store.get(target).balance_usd:.2f}", form, "users")

    def decide(rid: int, approve: bool, usd: float, admin_email: str) -> dict | None:
        """批 / 不批一条；批了就发额度，并把通知邮件排进队列。"""
        r = store.decide_request(rid, approve, usd, f"额度申请 #{rid} 批准（{admin_email}）")
        if r and approve and (u := store.get(r["email"])):
            r["mailed"] = queue_mail(u.email, "credit_granted", store.mail_lang(u.email), amount=f"{usd:g}",
                                     balance=f"{max(u.balance_usd, 0):.2f}")
        return r

    @app.post("/_gw/admin/request")
    async def admin_request(request: Request):
        """批 / 不批一条额度申请；批了就发额度并邮件告诉对方。"""
        got = await admin_form(request)
        if got is None:
            return Response(status_code=404)
        admin_email, form = got
        try:
            rid, usd = int(form.get("id") or 0), float(form.get("usd") or 0)
        except ValueError:
            return back("申请编号或金额不对", form, "requests")
        approve = form.get("action") == "approve"
        if approve and not 0 < usd <= 100:
            return back("没批：金额须在 0–100 之间", form, "requests")
        r = decide(rid, approve, usd, admin_email)
        if r is None:
            return back("这条申请已处理过或不存在", form, "requests")
        if not approve:
            return back(f"已婉拒 {mask(r['email'])} 的申请（应用里会显示「未批准」）", form, "requests")
        return back(f"已批：给 {mask(r['email'])} 加 ${usd:g}" + ("，邮件已排队发送" if r.get("mailed") else ""),
                    form, "requests")

    @app.post("/_gw/admin/requests")
    async def admin_requests_batch(request: Request):
        """额度申请批量操作：勾选的一起按同一金额批准，或一起不批。"""
        got = await admin_form(request)
        if got is None:
            return Response(status_code=404)
        admin_email, form = got
        # 行内按钮 act="approve:编号"（金额取那一行的 usd_编号）；表头按钮 act="approve"，对象是勾选的 sel
        action, _, one = str(form.get("act") or "").partition(":")
        try:
            ids = [int(one)] if one else sorted({int(v) for v in form.getlist("sel")})
            usd = float(form.get(f"usd_{one}" if one else "usd") or 0)
        except ValueError:
            return back("申请编号或金额不对", form, "requests")
        if not ids:
            return back("没勾选任何申请", form, "requests")
        approve = action == "approve"
        if approve and not 0 < usd <= 100:
            return back("没批：金额须在 0–100 之间", form, "requests")
        done = [r for r in (decide(i, approve, usd, admin_email) for i in ids) if r]
        skipped = f"（{len(ids) - len(done)} 条已处理过，跳过）" if len(done) < len(ids) else ""
        if not approve:
            return back(f"已婉拒 {len(done)} 条申请{skipped}", form, "requests")
        return back(f"已批 {len(done)} 条，每人加 ${usd:g}{skipped}"
                    + (f"，{sum(1 for r in done if r.get('mailed'))} 封通知邮件已排队" if done else ""), form, "requests")

    # ---------- 其余一切：转发到这个人自己的 machine ----------

    seen_days: set[tuple[str, str]] = set()

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

        day = datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m-%d")
        if (email, day) not in seen_days:                      # 每人每天写一次库：后台的活跃曲线
            store.touch_day(email, day)
            note_geo(email, request)                            # 地点也每天更新一次
            seen_days.add((email, day))
        url = f"http://{fly.address(user.machine_id)}:8899/{path}"
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
        headers["host"] = settings.public_host
        if request.cookies.get("jl_lang") in ("zh", "en"):   # 首页选过的语言带进引擎（设置里改的仍优先）
            headers["accept-language"] = request.cookies["jl_lang"]
        headers["x-joblander-gateway"] = user.gateway_token
        chosen = request.cookies.get("jl_lang_set")
        if chosen in ("zh", "en"):
            headers["x-joblander-set-lang"] = chosen
        sleeper.seen(email)
        try:
            await sleeper.ensure_awake(user)
        except Exception:                                       # noqa: BLE001  叫不醒就按连不上处理
            pass
        body_bytes = await request.body()                       # 先读出来：连不上要叫醒后重发一次
        req = http.build_request(request.method, url, params=request.query_params,
                                 headers=headers, content=body_bytes)
        try:
            try:
                resp = await http.send(req, stream=True)
            except httpx.ConnectError:
                try:
                    woke = await sleeper.recover(user)
                except Exception:                               # noqa: BLE001
                    woke = False
                if not woke:                                    # 不是在睡：真连不上
                    raise
                resp = await http.send(http.build_request(request.method, url, params=request.query_params,
                                                          headers=headers, content=body_bytes), stream=True)
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
