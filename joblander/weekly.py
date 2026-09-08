"""W11 周报 + W12 优先级再平衡 + W15 流失归因（零 LLM 统计层 + 可选 LLM 叙事层）。

数据源：Event Log（genesis 起算的漏斗）+ tracker 投影 + Playbook 战况。
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from joblander.tz import LOCAL_TZ as SGT   # 单一来源，JOBLANDER_TZ 可覆盖
TERMINAL = {"Terminated", "Not Apply", "Rejected", "Withdrawn"}
ACTIVE = {"Added", "Dream", "In Consideration", "To Apply", "Screening Called",
          "Applied", "Interview Scheduled", "Interview Completed"}


def funnel_stats(rows: list[dict]) -> dict[str, Any]:
    by_status = Counter(r.get("Status") or "?" for r in rows)
    return {
        "total": len(rows),
        "active": sum(v for k, v in by_status.items() if k in ACTIVE),
        "terminal": sum(v for k, v in by_status.items() if k in TERMINAL),
        "by_status": dict(by_status.most_common()),
    }


def playbook_health(cfg) -> list[dict[str, Any]]:
    """每模式最近战况 + 连续 miss 检测（W15 跨公司模式告警）。"""
    path = cfg.workspace_dir / "03-materials" / "playbook.yaml"
    if not path.exists():
        return []
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    out = []
    for p in entries:
        engs = sorted(p.get("engagements", []), key=lambda e: str(e.get("date", "")))
        outcomes = [e.get("outcome") for e in engs]
        tail_miss = 0
        for o in reversed(outcomes):
            if o == "miss":
                tail_miss += 1
            elif o in ("hit", "partial"):
                break
        out.append({"id": p.get("id"), "pattern": p.get("pattern"),
                    "status": p.get("status"), "n": len(engs),
                    "recent": outcomes[-3:], "consecutive_miss": tail_miss,
                    "alert": tail_miss >= 2})
    return out


def priority_proposal(rows: list[dict]) -> list[str]:
    """W12 v0：组合层信号（启发式，判断权在人）。"""
    sig: list[str] = []
    high = [r for r in rows if r.get("Priority") == "High" and r.get("Status") in ACTIVE]
    stalled = [r for r in high if not r.get("Follow-up Reminder")]
    for r in stalled:
        sig.append(f"High 无 follow-up：{r.get('Company')} —— 要么定日期要么降级")
    waiting = [r for r in rows if r.get("Status") == "Interview Scheduled"]
    if len(waiting) < 3:
        sig.append(f"排面中的仗只剩 {len(waiting)} 场 —— 考虑把本周小时数向找新机会倾斜")
    added = [r for r in rows if r.get("Status") == "Added"]
    for r in added:
        sig.append(f"入池未评估：{r.get('Company')} —— 公司页点「评估匹配」或关闭")
    return sig


STAGE_GROUPS = [("面试中", {"Interview Scheduled", "Interview Completed"}),
                ("申请 / 初筛", {"Applied", "Screening Called"}),
                ("待申请", {"To Apply"}),
                ("评估中", {"In Consideration"}),
                ("线索", {"Added", "Dream"}),
                ("Offer", {"Offer Received"})]


def week_recap(cfg, rows: list[dict], since_date: str) -> dict[str, list]:
    """本周战果 = 有实质进展的事：打完的面试/通话、阶段推进、关闭。
    新增线索不算战果（那是弹药，归战线现状）。统计按 payload.date（仗打的日子），
    不按事件 ts（录入时刻）——历史回溯的条目因此正确落回它们的周。"""
    from joblander.eventlog import EventLog
    by_pid = {(r.get("notion_page_id") or "").replace("-", ""): r for r in rows}
    interviews: dict[tuple, dict] = {}
    moves: dict[str, dict] = {}
    closes: dict[str, dict] = {}

    def _status_change(company, new, old=None):
        item = {"company": company, "to": new, "from": old}
        (closes if new in TERMINAL else moves)[company] = item     # 每公司只留最终态

    log = EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl")
    for e in log.events():
        k, p = e["kind"], e.get("payload") or {}
        if k == "company.timeline_added":
            d = p.get("date") or e["ts"][:10]
            if d < since_date:
                continue
            # 同一条目的后续纠正事件覆盖前值（kind 可能被重分类，包括改回 note）
            key = (p.get("company"), d, (p.get("title") or "").casefold())
            interviews[key] = {"company": p.get("company"), "date": d,
                               "title": p.get("title") or "", "kind": p.get("kind")}
        elif e["ts"][:10] >= since_date:
            if k == "row.edited" and p.get("field") == "Status" and p.get("value"):
                co = (by_pid.get((p.get("page_id") or "").replace("-", "")) or {}) \
                    .get("Company") or "（行）"
                _status_change(co, p["value"])
            elif k == "notion.edited":
                for c in (p.get("changes") or ([p] if p.get("field") else [])):
                    if c.get("field") == "Status" and c.get("new"):
                        _status_change(c.get("company") or "（行）", c["new"], c.get("old"))
    from joblander.company import BATTLE_KINDS
    ivs = sorted((v for v in interviews.values() if v.get("kind") in BATTLE_KINDS),
                 key=lambda x: x["date"])
    return {"interviews": ivs, "moves": list(moves.values()),
            "closes": list(closes.values())}


def week_review_corpus(cfg, since_date: str) -> list[dict]:
    """本周全部纪要与复盘（复盘提炼的原料）：扫全部公司档案时间线。"""
    from joblander.company import BATTLE_KINDS, local_entries
    base = cfg.workspace_dir / "18-companies"
    out: list[dict] = []
    if not base.exists():
        return out
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        for e in local_entries(cfg, d.name):
            if e.get("date", "") >= since_date and e.get("kind") in BATTLE_KINDS:
                out.append({"company": d.name, "date": e.get("date"),
                            "title": e.get("title") or "",
                            "record": (e.get("content_md") or "")[:3000],
                            "my_review": (e.get("my_review") or {}).get("text", "")})
    return sorted(out, key=lambda x: x["date"])


REVIEW_SYSTEM = """你是他的求职复盘教练。输入本周每场面试/通话的原始纪要与本人复盘。
输出严格 JSON（中文）：
{"good": [{"where": "公司 · 场次", "what": "具体哪个问题/环节答得好（引用原话或场景）", "why": "为什么有效"}],
 "bad": [{"where": "公司 · 场次", "what": "具体卡壳/失分点", "fix": "下次怎么改（可执行的一句）"}],
 "focus": "下周最该专练的一件事（一句话）"}
纪律：只从纪要取材，具体到问题与说法，不许泛泛而谈；没有记录支撑的不写；good/bad 各最多 4 条。"""


def synthesize_review(llm, corpus: list[dict]) -> dict | None:
    if not corpus or llm is None:
        return None
    try:
        from joblander.scribe import _strip_fences
        raw = llm.generate(json.dumps(corpus, ensure_ascii=False)[:24000],
                           system=REVIEW_SYSTEM, json_mode=True)
        return json.loads(_strip_fences(raw))
    except Exception:
        return None


def _cal_interviews(cfg, today: str) -> list[dict]:
    try:
        state = json.loads((cfg.workspace_dir / "08-events" / "daemon-state.json")
                           .read_text(encoding="utf-8"))
        return [e for e in (state.get("calendar_cache") or {}).get("events", [])
                if e.get("kind") == "interview" and str(e.get("start", ""))[:10] >= today]
    except Exception:
        return []


def next_battles(cfg, rows: list[dict], today: str) -> list[dict]:
    """下周的仗 = tracker（Interview Scheduled）∪ 日历（interview 事件）双源合并。
    单看日历会漏（事件没建），单看 tracker 会缺时间——都列，缺口标出来。"""
    cal = _cal_interviews(cfg, today)
    battles: list[dict] = []
    matched_titles: set[str] = set()
    for r in rows:
        if r.get("Status") != "Interview Scheduled":
            continue
        short = (r.get("Company") or "").split("（")[0].strip().casefold()
        ev = next((e for e in cal if short and short in (e.get("title") or "").casefold()),
                  None)
        if ev:
            matched_titles.add(ev.get("title") or "")
        when = str(ev["start"])[5:16].replace("T", " ") if ev \
            else (r.get("Follow-up Reminder") or "时间待定")
        prep: list[str] = []
        slug = (r.get("Company") or "").split("（")[0].strip().replace(" ", "-").replace("/", "-")
        bdir = cfg.workspace_dir / "10-briefs"
        fresh_brief = bdir.exists() and any(
            f.name >= f"{today[:8]}" for f in bdir.glob(f"*{slug}*.md")) if slug else False
        if not fresh_brief:
            prep.append("生成 brief")
        jd_dir = cfg.workspace_dir / "18-companies" / slug / "jd"
        if not (jd_dir.exists() and any(jd_dir.iterdir())):
            prep.append("补 JD")
        if not ev:
            prep.append("⚠️ 日历缺事件——指挥中心排期缺口里一键补")
        battles.append({"company": r.get("Company"), "when": when,
                        "next": r.get("Next Steps") or "", "prep": prep})
    for e in cal:                                 # 日历有、tracker 没跟上的
        if (e.get("title") or "") not in matched_titles:
            battles.append({"company": e.get("title"), "when":
                            str(e["start"])[5:16].replace("T", " "),
                            "next": "", "prep": ["⚠️ tracker 未标 Interview Scheduled——已提同步提案"]})
    return sorted(battles, key=lambda b: ("9" if "待定" in b["when"] else "0") + b["when"])


def next_three(cfg, rows: list[dict], health: list[dict], today: str,
               focus: str = "") -> list[str]:
    """下周三件事（面试与备战已单列成段，这里不重复）：逾期推进 > 专练 > 清高分线索 > 补管道。"""
    picks: list[str] = []
    overdue = sorted([r for r in rows if r.get("Status") in ACTIVE
                      and (r.get("Follow-up Reminder") or "9999") < today],
                     key=lambda r: r.get("Follow-up Reminder") or "")
    if overdue:
        r = overdue[0]
        picks.append(f"▶ 推进：{r.get('Company')} 逾期最久（{r.get('Follow-up Reminder')}）"
                     f"——{r.get('Next Steps') or '定下一步'}")
    if focus:
        picks.append(f"🎯 专练：{focus}")
    else:
        worst = next((h for h in health if h["alert"]), None)
        if worst:
            picks.append(f"🩹 修短板：「{worst['pattern']}」已连续 "
                         f"{worst['consecutive_miss']} miss——上场前把最佳答案再排练一遍")
    try:
        from joblander.applyops import list_pending
        hot = [p for p in list_pending(cfg) if p.get("kind") == "lead.intake"
               and ((p.get("fit") or {}).get("fit") or 0) >= 4]
        if hot:
            picks.append(f"📥 清决策：{len(hot)} 条 fit≥4 的新机会在等——新机会 5 分钟清完")
    except Exception:
        pass
    scheduled = [r for r in rows if r.get("Status") == "Interview Scheduled"]
    if len(scheduled) < 3:
        picks.append(f"🧲 补管道：排面中的仗只剩 {len(scheduled)} 场——本周给找新机会多留点时间")
    return picks[:3]


def build_weekly(cfg, llm=None) -> tuple[Path, str]:
    from joblander.eventlog import EventLog
    from joblander.prep import _load_projection

    now = datetime.now(SGT)
    today = now.strftime("%Y-%m-%d")
    rows = _load_projection(cfg)
    # 2026-08-10 起 Notion 不做内容同步：时间线以本地档案为唯一事实源，不再周度回填
    funnel = funnel_stats(rows)
    health = playbook_health(cfg)
    signals = priority_proposal(rows)
    since = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    recap = week_recap(cfg, rows, since)
    corpus = week_review_corpus(cfg, since)
    review = synthesize_review(llm, corpus)
    battles = next_battles(cfg, rows, today)
    picks = next_three(cfg, rows, health, today,
                       focus=(review or {}).get("focus", ""))

    span = f"{since[5:]} ~ {now.strftime('%m-%d')}"
    summary = (f"本周 {len(recap['interviews'])} 场面试/通话、推进 {len(recap['moves'])} 家、"
               f"关闭 {len(recap['closes'])} 家；活跃 {funnel['active']} 家，"
               f"下周排面 {len(battles)} 场。")

    md = [f"# 周报 · {span}", f"> {summary}", "", "## 本周战果"]
    got = False
    for iv in recap["interviews"]:
        md.append(f"- 🎤 {iv['date'][5:]}｜{iv['company']}：{iv['title']}")
        got = True
    for m in recap["moves"]:
        arrow = f"{m['from']} → {m['to']}" if m.get("from") else f"→ {m['to']}"
        md.append(f"- ▶ {m['company']}：{arrow}")
        got = True
    for c in recap["closes"]:
        md.append(f"- 🪦 {c['company']}（{c['to']}）")
        got = True
    if not got:
        md.append("- 本周没有实质进展——这本身就是最重要的信号")

    md += ["", "## 下周的仗与备战"]
    for b in battles:
        line = f"- 🎤 **{b['when']}**｜{b['company']}"
        if b["next"]:
            line += f"｜{b['next']}"
        if b["prep"]:
            line += f"｜备战：{'、'.join(b['prep'])}"
        md.append(line)
    if not battles:
        md.append("- 下周没有已排面试——火力放在推进在途申请和补管道")

    md += ["", "## 战线现状"]
    parts = []
    for label, statuses in STAGE_GROUPS:
        n = sum(1 for r in rows if r.get("Status") in statuses)
        if n:
            parts.append(f"{label} {n}")
    md.append(f"- 活跃 {funnel['active']} 家：" + " ｜ ".join(parts))
    try:
        from joblander.applyops import list_pending
        leads = [p for p in list_pending(cfg) if p.get("kind") == "lead.intake"]
        hot = sum(1 for p in leads if ((p.get("fit") or {}).get("fit") or 0) >= 4)
        if leads:
            md.append(f"- 新机会待决策 {len(leads)} 条（fit≥4 有 {hot} 条）——弹药，不算战果")
    except Exception:
        pass
    md.append(f"- 累计关闭 {funnel['terminal']} 家（共接触 {funnel['total']} 家）")

    md += ["", f"## 本周复盘提炼（来自 {len(corpus)} 份纪要）"]
    if review:
        if review.get("good"):
            md.append("**答得好：**")
            md += [f"- 【{g.get('where','')}】{g.get('what','')}——{g.get('why','')}"
                   for g in review["good"]]
        if review.get("bad"):
            md.append("**待改进：**")
            md += [f"- 【{b_.get('where','')}】{b_.get('what','')} → 改：{b_.get('fix','')}"
                   for b_ in review["bad"]]
    elif corpus:
        md.append("（LLM 未配置——纪要清单如下，配置后自动提炼）")
        md += [f"- {c_['date'][5:]}｜{c_['company']}：{c_['title']}" for c_ in corpus]
    else:
        md.append("- 本周无纪要入档——有面必录，复盘才有原料")
    alerts = [h for h in health if h["alert"]]
    if alerts:
        md.append("")
        md.append("参考信号（Playbook 供对照，不替代复盘）：" + "；".join(
            f"「{h['pattern'][:26]}」连续 {h['consecutive_miss']} miss" for h in alerts))

    md += ["", "## 下周三件事（面试之外）"]
    md += [f"{i}. {p}" for i, p in enumerate(picks, 1)] or ["1. 无"]

    extra = [s for s in signals if not any(s[:12] in p for p in picks)]
    if extra:
        md += ["", "<details><summary>更多信号</summary>", ""]
        md += [f"- {s}" for s in extra]
        md += ["", "</details>"]

    text = "\n".join(md) + "\n"
    out_dir = cfg.workspace_dir / "13-daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{now.strftime('%Y-%m-%d')}-weekly.md"
    if out.exists():                               # 重生成不得吃掉他手写的段
        from joblander.daily import NOTES_HEADER, read_section
        notes = read_section(out, NOTES_HEADER)
        if notes:
            text += f"\n## {NOTES_HEADER}\n\n{notes}\n"
    out.write_text(text, encoding="utf-8")
    log = EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl")
    log.append("weekly.generated", "joblander.weekly",
               {"active": funnel["active"], "alerts": sum(1 for h in health if h["alert"])})
    return out, text
