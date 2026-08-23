"""晚间日记草稿 → 提案（他改两句定稿后落 13-daily 日报的「今日日记」段）。

素材只取**各公司档案今天的战线事件**（面试/通话/邮件/入池这类他打的仗）——
不吃系统事件流：字段修改、评估重算、画像重估、回溯这些「内部信息更新、
数据更新、系统开发进展」一概不进日记（2026-08-08 他定的边界）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

SGT = timezone(timedelta(hours=8))

# 战线事件：他与外界真实交手的记录。assessment/评估类是系统的数据更新，不算。
BATTLE_KINDS = {"interview", "call", "email", "note", "transcript", "intake",
                "application", "offer"}

DIARY_SYSTEM = """你是求职日记的代笔。输入今天各公司的战线事件与 pipeline 快照，输出一段中文日记草稿（markdown）。
规则：
- 以「### YYYY-MM-DD」开头；风格对齐既有日记：短句、要点式、公司名保留原文
- 分【进展】【明日优先级】两块：进展按公司叙述今天真实发生的事（谁面了、谁回了、聊了什么要点）；
  明日优先级从 follow-up 到期与明日场次推导，最多 4 条
- 只写输入里有依据的内容，不编造；系统性动作（数据同步、字段修改、评估重算）永远不写"""


def today_battle_events(cfg, date: str) -> list[dict]:
    """各公司档案今天的战线事件（日记素材，也供指挥中心直接展示）。"""
    from joblander.company import local_entries
    base = cfg.workspace_dir / "18-companies"
    out: list[dict] = []
    if not base.exists():
        return out
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        for e in local_entries(cfg, d.name):
            if e.get("date") == date and e.get("kind") in BATTLE_KINDS:
                out.append({"company": d.name, "kind": e.get("kind"),
                            "title": e.get("title") or "",
                            "summary": (e.get("summary") or
                                        (e.get("content_md") or "")[:300]),
                            "my_review": (e.get("my_review") or {}).get("text", "")[:200]})
    return out


def build_diary_draft(cfg, llm, today: str | None = None) -> Path | None:
    from joblander.eventlog import EventLog
    from joblander.prep import _load_projection

    now = datetime.now(SGT)
    today = today or now.strftime("%Y-%m-%d")
    log = EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl")

    battles = today_battle_events(cfg, today)
    if not battles:
        log.append("diary.skipped", "joblander.diary",
                   {"date": today, "why": "今天没有战线事件"})
        return None

    rows = _load_projection(cfg)
    tomorrow = (datetime.fromisoformat(today) + timedelta(days=1)).strftime("%Y-%m-%d")
    focus = [{k: r.get(k) for k in ("Company", "Status", "Priority", "Next Steps",
                                    "Follow-up Reminder")}
             for r in rows
             if (r.get("Follow-up Reminder") or "") <= tomorrow
             and r.get("Status") not in ("Terminated", "Not Apply", "Rejected", "Withdrawn")
             and r.get("Follow-up Reminder")]

    prompt = (f"今天：{today}\n"
              f"各公司战线事件：{json.dumps(battles, ensure_ascii=False)[:8000]}\n"
              f"明日前到期的 follow-up：{json.dumps(focus, ensure_ascii=False)[:2000]}")
    draft = llm.generate(prompt, system=DIARY_SYSTEM)

    proposal = {
        "kind": "diary.entry",
        "date": today,
        "notion_page_id": cfg.raw.get("notion", {}).get("diary_page_id"),
        "body_entry": draft.strip(),
        "approved": None,
    }
    out_dir = cfg.workspace_dir / "11-shadow"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{today}-diary-draft.json"
    out.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding="utf-8")
    log.append("diary.drafted", "joblander.diary",
               {"date": today, "battles": len(battles), "out": str(out)})
    return out
