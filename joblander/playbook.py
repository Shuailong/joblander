"""Playbook 存取与战况回写（F3 闭环：W9 复盘 → yaml → 告警 → brief 置顶）。

status 自动演化规则（可被人工改写，写回时尊重人工值以外只做建议性迁移）：
  连续 2+ miss → needs_work；最近 3 战 ≥2 hit 且无 tail miss → improving；
  连续 3+ hit → solid。人工设的 status 只会被「恶化」方向覆盖（升级告警），
  不会被自动「洗好」——变好由周报建议、人来定。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import yaml

SGT = timezone(timedelta(hours=8))
VALID_OUTCOMES = {"hit", "miss", "partial", "untested"}


def _path(cfg) -> Path:
    return cfg.workspace_dir / "03-materials" / "playbook.yaml"


def load(cfg) -> list[dict[str, Any]]:
    p = _path(cfg)
    if not p.exists():
        return []
    return yaml.safe_load(p.read_text(encoding="utf-8")) or []


def save(cfg, entries: list[dict[str, Any]]) -> None:
    p = _path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(entries, allow_unicode=True, sort_keys=False, width=100),
                 encoding="utf-8")


def _tail_miss(outcomes: list[str]) -> int:
    n = 0
    for o in reversed(outcomes):
        if o == "miss":
            n += 1
        elif o in ("hit", "partial"):
            break
    return n


def suggest_status(entry: dict[str, Any]) -> str:
    outcomes = [e.get("outcome") for e in entry.get("engagements", [])
                if e.get("outcome") in ("hit", "miss", "partial")]
    cur = entry.get("status", "watch")
    if _tail_miss(outcomes) >= 2:
        return "needs_work"
    tail_hit = 0
    for o in reversed(outcomes):
        if o == "hit":
            tail_hit += 1
        else:
            break
    if tail_hit >= 3:
        return "solid"
    if len(outcomes) >= 3 and sum(1 for o in outcomes[-3:] if o == "hit") >= 2:
        return "improving"
    return cur


def apply_updates(cfg, updates: list[dict[str, Any]], company: str = "",
                  date: str | None = None) -> dict[str, Any]:
    """把 Scribe 的 playbook_updates 写入 yaml。返回 {applied, alerts, unknown_ids}。"""
    entries = load(cfg)
    by_id = {e.get("id"): e for e in entries}
    date = date or datetime.now(SGT).strftime("%Y-%m-%d")
    applied, alerts, unknown = [], [], []

    for u in updates or []:
        pid, outcome = u.get("id"), u.get("outcome")
        if pid not in by_id or outcome not in VALID_OUTCOMES:
            unknown.append(pid)
            continue
        entry = by_id[pid]
        engs = entry.setdefault("engagements", [])
        rec = {"date": date, "company_ref": company or u.get("company", ""),
               "outcome": outcome, "note": (u.get("note") or "")[:200]}
        if any(e.get("date") == rec["date"] and e.get("company_ref") == rec["company_ref"]
               and e.get("outcome") == outcome for e in engs):
            continue                                 # 幂等：同日同司同果不重复入账
        engs.append(rec)
        applied.append(pid)

        suggested = suggest_status(entry)
        if suggested == "needs_work" and entry.get("status") != "needs_work":
            entry["status"] = "needs_work"           # 恶化方向自动覆盖（告警）
            alerts.append(f"{pid} 连续 miss → needs_work（本周必修）")
        elif suggested != entry.get("status"):
            entry["_suggested_status"] = suggested   # 变好方向只挂建议，人来定

    if applied:
        save(cfg, entries)
        from joblander.eventlog import EventLog
        EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
            "playbook.updated", "joblander.playbook",
            {"applied": applied, "alerts": alerts, "company": company})
    return {"applied": applied, "alerts": alerts, "unknown_ids": unknown}
