"""Gmail 只读同步（W1 自动通道）— Google OAuth Device/InstalledApp 流，纯 stdlib。

权限：scope 固定 gmail.readonly（CLAUDE.md 红线：Gmail 只读）。
凭证：workspace/.credentials/（gitignored 的私有目录）。
用法：
  python -m joblander gmail-auth    # 一次性：打印授权 URL → 粘贴 code
  python -m joblander gmail-scan    # 增量扫描 → 机会候选 → intake 提案
"""

from __future__ import annotations

import base64
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from joblander.tz import LOCAL_TZ as SGT   # 单一来源，JOBLANDER_TZ 可覆盖
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_CAL_RO = "https://www.googleapis.com/auth/calendar.readonly"
SCOPE_CAL_RW = "https://www.googleapis.com/auth/calendar.events"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
LOOPBACK_PORT = 8765
REDIRECT_LOOPBACK = f"http://localhost:{LOOPBACK_PORT}"


def _cred_dir(cfg) -> Path:
    d = cfg.workspace_dir / ".credentials"
    d.mkdir(parents=True, exist_ok=True)
    d.chmod(0o700)                      # 里面是长期有效的 OAuth refresh token
    return d


def write_token(path: Path, tok: dict) -> None:
    """token 落盘限本人可读——默认 0644 等于把邮箱与日历的长期凭证摊给同机所有账户。"""
    path.write_text(json.dumps(tok), encoding="utf-8")
    path.chmod(0o600)


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def auth_url(cfg, scopes: str | None = None) -> str:
    """第一步：生成授权 URL（loopback 流；OOB 已被 Google 封杀）。"""
    g = cfg.raw.get("gmail", {})
    if not g.get("client_id"):
        raise RuntimeError("config.gmail.client_id 缺失——GCP Console → APIs → Credentials → "
                           "OAuth client ID (Desktop app)，把 client_id/client_secret 填进私有 config")
    params = {"client_id": g["client_id"], "redirect_uri": REDIRECT_LOOPBACK,
              "response_type": "code",
              "scope": scopes or f"{SCOPE} {SCOPE_CAL_RO} {SCOPE_CAL_RW}",
              "access_type": "offline", "prompt": "consent"}
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def wait_for_code(timeout: int = 300) -> str:
    """本地起一次性 HTTP 服务接 Google 回跳的 ?code=。"""
    import http.server

    captured: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            captured["code"] = (qs.get("code") or [""])[0]
            captured["error"] = (qs.get("error") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>joblander 授权完成，可以关掉这个页面了 ✅</h2>".encode())

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", LOOPBACK_PORT), Handler)
    server.timeout = timeout
    server.handle_request()
    server.server_close()
    if captured.get("error"):
        raise RuntimeError(f"授权被拒：{captured['error']}")
    if not captured.get("code"):
        raise RuntimeError("超时未收到授权回跳")
    return captured["code"]


def exchange_code(cfg, code: str) -> Path:
    """第二步：授权 code → refresh token 落盘（gmail 与 calendar 共用同一 token）。"""
    g = cfg.raw["gmail"]
    tok = _post_form(TOKEN_URL, {
        "client_id": g["client_id"], "client_secret": g["client_secret"],
        "code": code.strip(), "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_LOOPBACK})
    path = _cred_dir(cfg) / "gmail_token.json"
    write_token(path, tok)
    write_token(_cred_dir(cfg) / "calendar_token.json", tok)
    return path


def _access_token(cfg) -> str:
    g = cfg.raw["gmail"]
    path = _cred_dir(cfg) / "gmail_token.json"
    tok = json.loads(path.read_text(encoding="utf-8"))
    if tok.get("_expiry", 0) > time.time() + 60 and tok.get("access_token"):
        return tok["access_token"]
    fresh = _post_form(TOKEN_URL, {
        "client_id": g["client_id"], "client_secret": g["client_secret"],
        "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    tok.update(fresh)
    tok["_expiry"] = time.time() + int(fresh.get("expires_in", 3600))
    write_token(path, tok)
    return tok["access_token"]


def _api(cfg, path: str) -> dict:
    req = urllib.request.Request(
        f"https://gmail.googleapis.com/gmail/v1/users/me{path}",
        headers={"Authorization": f"Bearer {_access_token(cfg)}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _extract_text(payload: dict) -> str:
    """message payload → 纯文本（读全文，不用 snippet——摘要会截断关键信息）。"""
    out: list[str] = []

    def walk(part: dict):
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime.startswith("text/"):
            text = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            if mime == "text/html":
                import re
                text = re.sub(r"<[^>]+>", " ", text)
            out.append(text)
        for p in part.get("parts", []) or []:
            walk(p)

    walk(payload)
    return "\n".join(out)


OPP_QUERY = ('newer_than:{days}d (recruiter OR opportunity OR interview OR "job description" '
             'OR 岗位 OR 面试 OR 内推 OR offer OR hiring) -category:promotions')


def scan(cfg, llm, days: int = 3, limit: int = 20) -> list[Path]:
    """增量扫描 → 每封候选邮件走 Scout intake（提案制，不建行）。幂等键 = gmail message id。"""
    from joblander.eventlog import EventLog
    from joblander.scout import intake

    log = EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl")
    seen = {e["payload"].get("gmail_id") for e in log.events()
            if e["kind"] == "gmail.message_scanned"}

    q = urllib.parse.quote(OPP_QUERY.format(days=days))
    listing = _api(cfg, f"/messages?q={q}&maxResults={limit}")
    proposals: list[Path] = []
    for m in listing.get("messages", []):
        if m["id"] in seen:
            continue
        full = _api(cfg, f"/messages/{m['id']}?format=full")
        headers = {h["name"].lower(): h["value"]
                   for h in full.get("payload", {}).get("headers", [])}
        text = _extract_text(full.get("payload", {}))
        body = (f"From: {headers.get('from','?')}\nSubject: {headers.get('subject','?')}\n"
                f"Date: {headers.get('date','?')}\n\n{text}")
        out = intake(cfg, llm, body, source_hint="gmail")
        if out is not None:                      # None = 噪音闸拦下（无公司无岗位）
            proposals.append(out)
        log.append("gmail.message_scanned", "joblander.gmail",
                   {"gmail_id": m["id"], "subject": headers.get("subject", "")[:80]})
    return proposals
