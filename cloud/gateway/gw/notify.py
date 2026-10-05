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
