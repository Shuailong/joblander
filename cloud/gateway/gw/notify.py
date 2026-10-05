"""反馈邮件：经 Resend 发到管理员邮箱，reply-to 设成反馈人——在邮箱里直接回复就到对方。

没配 RESEND_API_KEY 时不发（反馈照样存库，gw.cli feedback 可看）——邮件是通知，不是存储。
"""

from __future__ import annotations

import html

import httpx

RESEND_URL = "https://api.resend.com/emails"


async def send_feedback(http: httpx.AsyncClient, api_key: str, to: str, *, sender: str,
                        user: str, message: str, page: str, lang: str, ua: str, fid: int) -> bool:
    if not (api_key and to):
        return False
    body = (f"<p><b>{html.escape(user)}</b> sent feedback (#{fid})</p>"
            f"<blockquote style='white-space:pre-wrap;border-left:3px solid #0E6E62;padding-left:10px'>"
            f"{html.escape(message)}</blockquote>"
            f"<p style='color:#6F6D64;font-size:12px'>page: {html.escape(page)} · UI: {html.escape(lang)}<br>"
            f"{html.escape(ua)}</p>")
    r = await http.post(RESEND_URL, headers={"Authorization": f"Bearer {api_key}"}, json={
        "from": sender, "to": [to], "reply_to": user,
        "subject": f"[joblander feedback] {message.strip().splitlines()[0][:60]}",
        "html": body})
    return r.status_code < 300


async def send_blocked(http: httpx.AsyncClient, api_key: str, to: str, *, sender: str,
                       user: str, lang: str) -> bool:
    """没在邀请名单的人来登录：通知管理员一次（reply-to 是对方，邀请完可以直接回信）。"""
    if not (api_key and to):
        return False
    cmd = f'fly ssh console -a joblander-gw -C "python -m gw.cli invite {user}"'
    body = (f"<p><b>{html.escape(user)}</b> tried to sign in but isn't on the invite list (UI: {html.escape(lang)}).</p>"
            f"<p>To let them in:</p><pre style='background:#F4F6F3;padding:10px;border-radius:6px'>"
            f"{html.escape(cmd)}</pre>"
            f"<p style='color:#6F6D64;font-size:12px'>Not someone you know? "
            f"<code>python -m gw.cli dismiss {html.escape(user)}</code> clears the record. "
            f"Repeat attempts won't email again — see <code>gw.cli blocked</code>.</p>")
    r = await http.post(RESEND_URL, headers={"Authorization": f"Bearer {api_key}"}, json={
        "from": sender, "to": [to], "reply_to": user,
        "subject": f"[joblander] {user} wants in", "html": body})
    return r.status_code < 300


# ---------- 发给用户本人的邮件（需要已验证的发件域名：MAIL_FROM） ----------

APP_URL = "https://app.ailayoff.me"

_USER = {
    "waitlisted": {
        "zh": ("已收到你的内测申请",
               "<p>你好，</p><p>你刚用 <b>{email}</b> 登录 joblander，目前还不在内测名单里。申请我已经收到，"
               "加上后会再发一封邮件通知你。</p><p>有问题直接回复这封邮件。</p>"),
        "en": ("We've got your beta request",
               "<p>Hi,</p><p>You just tried to sign in to joblander as <b>{email}</b>, which isn't on the beta list yet. "
               "I've got your request and will email you again once you're in.</p><p>Questions? Just reply to this email.</p>"),
    },
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
               "<p>Want to keep going during the beta? Just reply to this email.</p>"
               "<p><a href='{url}/_gw/account'>See usage</a></p>"),
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


async def send_user(http: httpx.AsyncClient, api_key: str, sender: str, reply_to: str, *,
                    to: str, kind: str, lang: str | None, **ctx) -> bool:
    if not (api_key and sender):
        return False
    subject, body = render_user(kind, lang, email=to, **ctx)
    msg = {"from": sender, "to": [to], "subject": subject, "html": body}
    if reply_to:
        msg["reply_to"] = reply_to
    r = await http.post(RESEND_URL, headers={"Authorization": f"Bearer {api_key}"}, json=msg)
    return r.status_code < 300
