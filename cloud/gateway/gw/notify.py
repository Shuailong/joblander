"""邮件（经 Resend）：给管理员的每日汇总与 AI 故障告警，给用户本人的邀请 / 额度通知。

被拦的申请、额度申请、反馈不再逐条发信（量一大就撞 Resend 的发送上限），每天汇总成一封给管理员。
没配 RESEND_API_KEY 时不发（内容照样存库，后台与 gw.cli 可看）——邮件是通知，不是存储。
"""

from __future__ import annotations

import html

import httpx

RESEND_URL = "https://api.resend.com/emails"


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def render_digest(d: dict, *, day: str) -> tuple[str, str] | None:
    """每日汇总：新被拦的人、新额度申请、新反馈合成一封。都没有就不发（返回 None）。"""
    blocked, reqs, fb = d["blocked"], d["requests"], d["feedback"]
    if not (blocked or reqs or fb):
        return None
    quote = "white-space:pre-wrap;border-left:3px solid #0E6E62;padding-left:10px;margin:4px 0 12px"
    parts = [f"<p>joblander · {_esc(day)} 的汇总（过去一天）。"
             f"<a href='{APP_URL}/_gw/admin'>打开后台</a>批量处理。</p>"]
    if blocked:
        rows = "".join(f"<li>{_esc(b['email'])} <span style='color:#6F6D64'>({_esc(b['lang'] or '—')})</span></li>"
                       for b in blocked[:200])
        more = f"<li>……还有 {len(blocked) - 200} 人</li>" if len(blocked) > 200 else ""
        parts.append(f"<h3>新的内测申请 {len(blocked)} 人 <small style='color:#6F6D64'>（名单里共 {d['waiting']} 人待处理）"
                     f"</small></h3><ul>{rows}{more}</ul>"
                     f"<p><a href='{APP_URL}/_gw/admin#waitlist'>去后台批量邀请</a></p>")
    if reqs:
        items = "".join(f"<p><b>{_esc(r['email'])}</b> #{r['id']} · 余额 ${(r['credit_usd'] or 0) - (r['spent_usd'] or 0):.2f}"
                        f"</p><blockquote style='{quote}'>{_esc(r['message'][:600])}</blockquote>" for r in reqs[:50])
        parts.append(f"<h3>新的额度申请 {len(reqs)} 条 <small style='color:#6F6D64'>（共 {d['pending']} 条待批）</small></h3>"
                     f"{items}<p><a href='{APP_URL}/_gw/admin#requests'>去后台批量批准</a></p>")
    if fb:
        items = "".join(f"<p><b>{_esc(f['email'])}</b> <span style='color:#6F6D64'>#{f['id']} · {_esc(f['page'])}</span></p>"
                        f"<blockquote style='{quote}'>{_esc(f['message'][:1500])}</blockquote>" for f in fb[:50])
        parts.append(f"<h3>新反馈 {len(fb)} 条</h3>{items}"
                     "<p style='color:#6F6D64;font-size:12px'>回复反馈：直接给对方邮箱写信。</p>")
    counts = [f"{n} {w}" for n, w in ((len(blocked), "人申请"), (len(reqs), "条额度申请"), (len(fb), "条反馈")) if n]
    return f"[joblander] 每日汇总 {day}：" + "、".join(counts), "".join(parts)


async def send_digest(http: httpx.AsyncClient, api_key: str, to: str, *, sender: str, d: dict, day: str) -> bool | None:
    """发给管理员的每日汇总；没内容返回 None（不发），发出 True，失败 False。"""
    if not (api_key and to):
        return False
    got = render_digest(d, day=day)
    if got is None:
        return None
    subject, body = got
    r = await http.post(RESEND_URL, headers={"Authorization": f"Bearer {api_key}"}, json={
        "from": sender, "to": [to], "subject": subject, "html": body})
    return r.status_code < 300


async def send_ai_alert(http: httpx.AsyncClient, api_key: str, to: str, *, sender: str,
                        status: int, kind: str, recent: int) -> bool:
    """上游 AI 调用开始失败（限流、额度耗尽、网络）：告诉管理员，别等用户来报。"""
    if not (api_key and to):
        return False
    hint = {"insufficient_quota": "The OpenAI account is out of credit — top up at platform.openai.com/settings/billing.",
            "rate_limit_exceeded": "OpenAI is rate-limiting the platform key — the app retries automatically; "
                                   "if it keeps happening, raise the usage tier."}.get(kind, "")
    body = (f"<p>Upstream AI calls are failing: <b>{status} {html.escape(kind)}</b> "
            f"({recent} failure(s) in the last hour).</p>"
            f"<p>{html.escape(hint)}</p>"
            f"<p><a href='{APP_URL}/_gw/admin'>Admin page</a></p>"
            "<p style='color:#6F6D64;font-size:12px'>At most one email per error type every 3 hours.</p>")
    r = await http.post(RESEND_URL, headers={"Authorization": f"Bearer {api_key}"}, json={
        "from": sender, "to": [to], "subject": f"[joblander] AI calls failing: {status} {kind}", "html": body})
    return r.status_code < 300


# ---------- 发给用户本人的邮件（需要已验证的发件域名：MAIL_FROM） ----------

APP_URL = "https://app.ailayoff.me"

_USER = {
    "invited": {
        "zh": ("你的 joblander 内测已开通",
               "<p>你好，</p><p><b>{email}</b> 已加入内测，现在就可以登录了：</p>"
               "<p><a href='{url}' style='display:inline-block;background:#0C7A68;color:#fff;padding:10px 18px;"
               "border-radius:8px;text-decoration:none'>打开 joblander</a></p>"
               "<p>用这个 Google 账号登录即可。第一次进去会花一两分钟准备你的独立空间，附送 AI 试用额度。</p>"
               "<p>用着有任何问题，界面里点「反馈」或直接回复这封邮件。</p>"),
        "en": ("You're in — joblander beta",
               "<p>Hi,</p><p><b>{email}</b> is now on the beta. You can sign in right away:</p>"
               "<p><a href='{url}' style='display:inline-block;background:#0C7A68;color:#fff;padding:10px 18px;"
               "border-radius:8px;text-decoration:none'>Open joblander</a></p>"
               "<p>Sign in with this Google account. The first visit takes a minute or two to set up your private "
               "workspace, and comes with free AI credit.</p>"
               "<p>Anything off? Use Feedback in the app or just reply to this email.</p>"),
    },
    "low_balance": {
        "zh": ("你的 AI 额度快用完了",
               "<p>你好，</p><p>你在 joblander 的 AI 额度只剩 <b>${balance}</b>。用完后评估、尽调、生成简历等 AI 功能会暂停，"
               "已有数据不受影响。</p><p>内测期间想继续用，直接回复这封邮件就行。</p>"
               "<p><a href='{url}/_gw/account'>查看用量</a></p>"),
        "en": ("Your AI credit is running low",
               "<p>Hi,</p><p>You have <b>${balance}</b> of AI credit left on joblander. Once it runs out, AI features "
               "(scoring, research, tailored CVs) pause; your data stays as is.</p>"
               "<p>Want to keep going during the beta? Click “Request more credit” under Settings › Account in the app, "
               "or just reply to this email.</p>"
               "<p><a href='{url}/_gw/account'>See usage</a></p>"),
    },
    "credit_granted": {
        "zh": ("你的 AI 额度已追加",
               "<p>你好，</p><p>你申请的额度批了：已给 <b>{email}</b> 追加 <b>${amount}</b>，现在余额 <b>${balance}</b>。"
               "暂停的 AI 功能可以接着用了。</p><p>谢谢你的反馈，有想法随时在应用里点「反馈」或回复这封邮件。</p>"
               "<p><a href='{url}'>打开 joblander</a></p>"),
        "en": ("More AI credit added",
               "<p>Hi,</p><p>Your request was approved: <b>${amount}</b> has been added to <b>{email}</b>, "
               "and your balance is now <b>${balance}</b>. Paused AI features work again.</p>"
               "<p>Thanks for the feedback — use Feedback in the app or reply to this email any time.</p>"
               "<p><a href='{url}'>Open joblander</a></p>"),
    },
}

_FOOT = ("<p style='color:#6F6D64;font-size:12px;margin-top:24px'>joblander · <a href='{url}/_gw/privacy'>"
         "{privacy}</a></p>")


def render_user(kind: str, lang: str | None, **ctx) -> tuple[str, str]:
    """(subject, html)。语言未知时中英都放。"""
    ctx = {k: html.escape(str(v)) for k, v in ctx.items()} | {"url": APP_URL}
    langs = [lang] if lang in ("zh", "en") else ["zh", "en"]
    parts = [_USER[kind][lg][1].format(**ctx) + _FOOT.format(url=APP_URL, privacy="隐私说明" if lg == "zh"
                                                             else "Privacy") for lg in langs]
    subject = " / ".join(_USER[kind][lg][0] for lg in langs)
    return subject, "<hr style='border:none;border-top:1px solid #ddd;margin:24px 0'>".join(parts)


async def post_user(http: httpx.AsyncClient, api_key: str, sender: str, reply_to: str, *,
                    to: str, kind: str, lang: str | None, **ctx) -> httpx.Response:
    """发一封给用户的信，原样返回 Resend 的响应（发信队列要看 429 是限流还是当日额度用完）。"""
    subject, body = render_user(kind, lang, email=to, **ctx)
    msg = {"from": sender, "to": [to], "subject": subject, "html": body}
    if reply_to:
        msg["reply_to"] = reply_to
    return await http.post(RESEND_URL, headers={"Authorization": f"Bearer {api_key}"}, json=msg)


async def send_user(http: httpx.AsyncClient, api_key: str, sender: str, reply_to: str, *,
                    to: str, kind: str, lang: str | None, **ctx) -> bool:
    if not (api_key and sender):
        return False
    r = await post_user(http, api_key, sender, reply_to, to=to, kind=kind, lang=lang, **ctx)
    return r.status_code < 300
