"""Calendar 同步（W6/W7 触发源）— 读 free-busy 与近程事件；写=确认制（ADR-10）。

复用 gmail_sync 的 OAuth 机制，scope 独立：
  读：calendar.readonly（默认）
  写：calendar.events —— 每次 create 前必须人工确认（--yes），且事件详情先打印
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from joblander.gmail_sync import TOKEN_URL, _cred_dir, _post_form

SGT = timezone(timedelta(hours=8))
SCOPE_RO = "https://www.googleapis.com/auth/calendar.readonly"
SCOPE_RW = "https://www.googleapis.com/auth/calendar.events"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
REDIRECT_OOB = "urn:ietf:wg:oauth:2.0:oob"


def auth_url(cfg, write: bool = False) -> str:
    g = cfg.raw.get("gmail", {})   # 同一个 GCP OAuth client
    scope = f"{SCOPE_RO} {SCOPE_RW}" if write else SCOPE_RO
    params = {"client_id": g["client_id"], "redirect_uri": REDIRECT_OOB,
              "response_type": "code", "scope": scope,
              "access_type": "offline", "prompt": "consent"}
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def exchange_code(cfg, code: str):
    g = cfg.raw["gmail"]
    tok = _post_form(TOKEN_URL, {
        "client_id": g["client_id"], "client_secret": g["client_secret"],
        "code": code.strip(), "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_OOB})
    path = _cred_dir(cfg) / "calendar_token.json"
    path.write_text(json.dumps(tok), encoding="utf-8")
    return path


def _access_token(cfg) -> str:
    import time
    g = cfg.raw["gmail"]
    path = _cred_dir(cfg) / "calendar_token.json"
    tok = json.loads(path.read_text(encoding="utf-8"))
    if tok.get("_expiry", 0) > time.time() + 60 and tok.get("access_token"):
        return tok["access_token"]
    fresh = _post_form(TOKEN_URL, {
        "client_id": g["client_id"], "client_secret": g["client_secret"],
        "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    tok.update(fresh)
    tok["_expiry"] = time.time() + int(fresh.get("expires_in", 3600))
    path.write_text(json.dumps(tok), encoding="utf-8")
    return tok["access_token"]


def _api(cfg, method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"https://www.googleapis.com/calendar/v3{path}",
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {_access_token(cfg)}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def upcoming_events(cfg, days: int = 10) -> list[dict[str, Any]]:
    """近程事件 → Coordinator 的 existing 格式。"""
    now = datetime.now(SGT)
    params = urllib.parse.urlencode({
        "timeMin": now.isoformat(), "timeMax": (now + timedelta(days=days)).isoformat(),
        "singleEvents": "true", "orderBy": "startTime", "maxResults": 50})
    data = _api(cfg, "GET", f"/calendars/primary/events?{params}")
    # 打标双腿：标题关键词 + 活跃公司名命中——「Chat with Kai @ Nimbus」这类标题
    # 靠公司名兜底。在源头统一打标，显示 / T-24h 弹药 / 排期对账全部一致。
    try:
        from joblander.prep import _load_projection
        co_names = [c for c in ((r.get("Company") or "").split("（")[0].split("(")[0]
                                .strip().casefold() for r in _load_projection(cfg))
                    if len(c) >= 2]
    except Exception:
        co_names = []
    out = []
    for ev in data.get("items", []):
        start = (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date")
        end = (ev.get("end") or {}).get("dateTime") or (ev.get("end") or {}).get("date")
        title = ev.get("summary", "?")
        low = title.lower()
        kind = "interview" if (any(w in low for w in
                                   ("interview", "面试", "screen", "call"))
                               or any(c in low for c in co_names)) else "block"
        out.append({"start": start, "end": end, "title": title, "kind": kind})
    return out


def create_event(cfg, title: str, start_iso: str, end_iso: str,
                 description: str = "", confirmed: bool = False) -> dict:
    """确认制写入：confirmed=False 只返回将要创建的事件详情（给人看），True 才真建。"""
    event = {"summary": title,
             "start": {"dateTime": start_iso, "timeZone": "Asia/Singapore"},
             "end": {"dateTime": end_iso, "timeZone": "Asia/Singapore"},
             "description": description}
    if not confirmed:
        return {"needs_confirmation": True, "event": event,
                "note": "ADR-10：创建前必须人工确认（--yes）"}
    created = _api(cfg, "POST", "/calendars/primary/events", event)
    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "calendar.event_created", "human_approved",
        {"title": title, "start": start_iso, "id": created.get("id")})
    return created
