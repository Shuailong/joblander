"""Coordinator 调度 — 时间域纯规则（W6 核心；日历传输层等 OAuth 后接入）。

规则即成文教训（Playbook P7 / DESIGN §7.4）：
①同日硬面 ≤2 ②场间缓冲 ≥30min ③技术轮前保护准备块 ④冲突检测。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

DEFAULT_RULES = {
    "min_buffer_min": 30,        # 场间缓冲（07-23 三连场教训）
    "max_hard_per_day": 2,       # 同日硬面上限
    "prep_gap_hours_tech": 4,    # 技术轮前的保护空档
}

HARD_KINDS = {"interview", "tech", "onsite"}


def _dt(v: str | datetime) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(v)


def check_candidate_slot(existing: list[dict[str, Any]], start: str | datetime,
                         end: str | datetime, kind: str = "interview",
                         rules: dict | None = None) -> list[str]:
    """候选时段 vs 既有日程 → 违例清单（空 = 可约）。

    existing: [{"start": iso, "end": iso, "kind": "interview|tech|call|block", "title": str}]
    """
    r = {**DEFAULT_RULES, **(rules or {})}
    s, e = _dt(start), _dt(end)
    violations: list[str] = []

    day_hard = 1 if kind in HARD_KINDS else 0
    for ev in existing:
        es, ee = _dt(ev["start"]), _dt(ev["end"])
        title = ev.get("title", "?")
        if s < ee and es < e:
            violations.append(f"重叠：与「{title}」（{es:%H:%M}–{ee:%H:%M}）冲突")
            continue
        gap_min = min(abs((s - ee).total_seconds()), abs((es - e).total_seconds())) / 60
        if gap_min < r["min_buffer_min"]:
            violations.append(f"缓冲不足：与「{title}」间隔 {gap_min:.0f}min < {r['min_buffer_min']}min")
        if ev.get("kind") in HARD_KINDS and es.date() == s.date():
            day_hard += 1
        if kind == "tech" and ee <= s:
            gap_h = (s - ee).total_seconds() / 3600
            if 0 <= gap_h < r["prep_gap_hours_tech"]:
                violations.append(
                    f"技术轮前保护块不足：「{title}」结束后仅 {gap_h:.1f}h < {r['prep_gap_hours_tech']}h")
    if kind in HARD_KINDS and day_hard > r["max_hard_per_day"]:
        violations.append(f"同日硬面 {day_hard} 场 > 上限 {r['max_hard_per_day']}（07-23/08-06 连场教训）")
    return violations


def pick_slot(existing: list[dict], candidates: list[tuple[str, str]],
              kind: str = "interview", rules: dict | None = None) -> list[dict]:
    """多个候选时段排序：违例少者优先（对方给 3 个时段选哪个）。"""
    scored = []
    for start, end in candidates:
        v = check_candidate_slot(existing, start, end, kind, rules)
        scored.append({"start": start, "end": end, "violations": v, "ok": not v})
    return sorted(scored, key=lambda x: len(x["violations"]))


EXTRACT_SYSTEM = """你是排期参谋。从面试邀约文本里抽取候选时段，输出 JSON：
{"slots": [{"start": "YYYY-MM-DDTHH:MM", "end": "YYYY-MM-DDTHH:MM", "label": "原文里的说法"}],
 "duration_min": 60, "language": "en|zh", "sender": "对方称呼（没有则空）", "notes": "时区等需要人复核的点"}
规则：
- 一切时间转换为新加坡时间（+08:00 不写偏移，输出裸 ISO）；邀约若给了别的时区，notes 里说明换算
- 「下周二」这类相对日期按给出的今天日期换算；只给日期没给钟点的，不要编造，放 notes
- end 缺失时用 start + duration_min（未写时长按 60 分钟）
- 抽不到任何完整时段就返回 {"slots": [], "notes": "原因"}"""

DRAFT_SYSTEM = """你是求职者本人的助理，代拟一封确认面试时间的短回复（求职者自己发送）。
要求：用邀约同语言；只确认推荐时段（一个），礼貌但不啰嗦（3 句内）；不编造任何事实；
若所有时段都有冲突，则礼貌提出改期并给出两个替代时段。只输出正文，不要主题行。"""


def suggest_slots(cfg, llm, invite_text: str, company: str = "",
                  cal_events: list[dict] | None = None) -> dict[str, Any]:
    """W6 排期参谋：邀约文本 → 抽取候选时段 → 对照日历跑规则 → 排序 + 回复草稿。

    cal_events 为 None 时拉真实日历；日历不可用时降级为「无冲突对照」并如实标注。
    """
    import json as _json
    from datetime import datetime as _dt

    now = _dt.now().astimezone()
    raw = llm.generate(
        f"今天是 {now:%Y-%m-%d}（{'周' + '一二三四五六日'[now.weekday()]}）。邀约原文：\n\n{invite_text}",
        system=EXTRACT_SYSTEM, json_mode=True)
    data = _json.loads(raw)
    slots = data.get("slots") or []

    calendar_ok = True
    if cal_events is None:
        try:
            from joblander.calendar_sync import upcoming_events
            cal_events = upcoming_events(cfg, days=14)
        except Exception:
            cal_events, calendar_ok = [], False

    cands = [(s["start"], s.get("end") or s["start"]) for s in slots
             if s.get("start") and len(s["start"]) >= 16]
    ranked = pick_slot(cal_events, cands, kind="interview") if cands else []
    for r in ranked:
        r["label"] = next((x.get("label", "") for x in slots if x.get("start") == r["start"]), "")

    best = next((r for r in ranked if r["ok"]), None)
    draft = ""
    if ranked:
        pick_line = (f"推荐时段：{best['start']}（无违例）" if best
                     else "所有候选时段都有冲突，需提出改期")
        draft = llm.generate(
            f"邀约原文：\n{invite_text}\n\n排期结论：{pick_line}\n"
            f"全部候选与违例：{_json.dumps(ranked, ensure_ascii=False)}\n"
            f"对方称呼：{data.get('sender') or '未知'}",
            system=DRAFT_SYSTEM)

    return {"slots": ranked, "best": best, "draft": draft.strip(),
            "extracted": data, "calendar_ok": calendar_ok, "company": company}


def format_slot_report(out: dict[str, Any]) -> str:
    """suggest_slots 结果 → 落档案的 markdown（时段对照表 + 草稿他发）。"""
    lines = ["**候选时段对照**（规则：同日硬面 ≤2 · 缓冲 ≥30min · 技术轮前保护 ≥4h）", ""]
    if not out["slots"]:
        lines.append(f"未抽取到完整时段。{(out['extracted'].get('notes') or '')}")
    for s in out["slots"]:
        mark = "✅ 可约" if s["ok"] else "⚠️ " + "；".join(s["violations"])
        lines.append(f"- `{s['start']}` {s.get('label', '')} — {mark}")
    if not out["calendar_ok"]:
        lines.append("\n> ⚠️ 日历不可用，本次未对照真实日程——确认前自查。")
    notes = out["extracted"].get("notes")
    if notes:
        lines.append(f"\n> 抽取备注：{notes}")
    if out["draft"]:
        lines += ["", "**回复草稿（你来发）**", "", "```", out["draft"], "```"]
    return "\n".join(lines)


def schedule_gaps(rows: list[dict], cal_events: list[dict], today: str) -> list[dict]:
    """tracker ↔ 日历错位检测（双向）：
    - tracker 排了面、日历没这场 → missing_calendar（提案建日历事件，人确认才写）
    - 日历有面试、tracker 没跟上 → tracker_behind（提案更新该公司行，公司页批）
    协调原则：日历管「什么时候」，tracker 管「打到哪了」——每场仗两边都得知道。"""
    ivs = [e for e in cal_events if e.get("kind") == "interview"
           and str(e.get("start", ""))[:10] >= today]
    gaps: list[dict] = []
    matched: set[str] = set()
    for r in rows:
        if r.get("Status") != "Interview Scheduled":
            continue
        short = (r.get("Company") or "").split("（")[0].strip().casefold()
        ev = next((e for e in ivs
                   if short and short in (e.get("title") or "").casefold()), None)
        if ev is None:
            gaps.append({"type": "missing_calendar", "company": r.get("Company"),
                         "page_id": r.get("notion_page_id"),
                         "date": r.get("Follow-up Reminder") or ""})
        else:
            matched.add(ev.get("title") or "")
    for e in ivs:
        if (e.get("title") or "") in matched:
            continue
        title_cf = (e.get("title") or "").casefold()
        row = next((r for r in rows
                    if (r.get("Company") or "").split("（")[0].strip()
                    and (r.get("Company") or "").split("（")[0].strip().casefold() in title_cf),
                   None)
        if row is not None and row.get("Status") not in ("Interview Scheduled",
                                                         "Interview Completed"):
            gaps.append({"type": "tracker_behind", "company": row.get("Company"),
                         "page_id": row.get("notion_page_id"),
                         "event_title": e.get("title"), "start": e.get("start")})
    return gaps
