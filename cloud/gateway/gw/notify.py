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
