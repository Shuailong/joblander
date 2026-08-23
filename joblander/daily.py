"""日报 — 13-daily/<date>.md 的分段模型与晨报拼装。

一份日报三段共存，各写各的、互不覆盖：
  ## 晨报 · 战线与待办    —— 08:15 自动（本模块 build_daily）
  ## 今日日记            —— AI 从各公司档案的今日战线事件起草 → 他改 → 定稿落此（diary.py + applyops）
  ## 我的手记            —— 他自己写的总结/感受，永远人工，任何自动重生成都必须保留

冷落安全（ADR-12）：日报是拉取式产物——生成后放在那里，永不催办。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

SGT = timezone(timedelta(hours=8))
ACTIVE = {"Added", "Dream", "In Consideration", "To Apply", "Screening Called",
          "Applied", "Interview Scheduled", "Interview Completed"}

MORNING_HEADER = "晨报 · 战线与待办"
DIARY_HEADER = "今日日记"
NOTES_HEADER = "我的手记"


# ---------- 分段模型（日报与周报文件共用） ----------

def parse_md_sections(text: str) -> tuple[str, list[dict]]:
    """按 `## ` 拆（沿用弹药库的段模型）：返回 (首个 ## 前的头部, [{header, body}])。"""
    head: list[str] = []
    secs: list[dict] = []
    cur: dict | None = None
    for line in (text or "").splitlines():
        if line.startswith("## "):
            cur = {"header": line[3:].strip(), "lines": []}
            secs.append(cur)
        elif cur is None:
            head.append(line)
        else:
            cur["lines"].append(line)
    for s in secs:
        s["body"] = "\n".join(s.pop("lines")).strip("\n")
    return "\n".join(head).rstrip(), secs


def rebuild_md(head: str, secs: list[dict]) -> str:
    parts = [head.rstrip()] if head.strip() else []
    parts += [f"## {s['header']}\n\n{s['body'].strip()}" for s in secs if s["body"].strip()]
    return "\n\n".join(parts) + "\n"


def daily_path(cfg, date: str) -> Path:
    return cfg.workspace_dir / "13-daily" / f"{date}.md"


def upsert_section(path: Path, header: str, body: str, *, title: str) -> Path:
    """替换或追加一个 `## header` 段，其余段原样保留；文件不存在则建骨架。"""
    head, secs = parse_md_sections(path.read_text(encoding="utf-8")) \
        if path.exists() else (title, [])
    hit = next((s for s in secs if s["header"] == header), None)
    if hit:
        hit["body"] = body
    else:
        secs.append({"header": header, "body": body})
    order = {MORNING_HEADER: 0, DIARY_HEADER: 1, NOTES_HEADER: 2}
    secs.sort(key=lambda s: order.get(s["header"], 9))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rebuild_md(head or title, secs), encoding="utf-8")
    return path


def read_section(path: Path, header: str) -> str:
    if not path.exists():
        return ""
    _, secs = parse_md_sections(path.read_text(encoding="utf-8"))
    return next((s["body"] for s in secs if s["header"] == header), "")


# ---------- 晨报 ----------

def _pending_proposals(cfg) -> list[dict]:
    out = []
    for d in ("11-shadow", "12-intake"):
        p = cfg.workspace_dir / d
        if not p.exists():
            continue
        for f in sorted(p.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("approved") is None:
                out.append({"file": str(f.name), "dir": d,
                            "company": data.get("company") or (data.get("lead") or {}).get("company")})
    return out


def build_daily(cfg, notion_client=None, today: str | None = None) -> tuple[Path, str]:
    """晨报段：战线状态 + 待办。只 upsert 自己的段——日记与手记永不被碰。"""
    from joblander.eventlog import EventLog
    from joblander.prep import _load_projection

    now = datetime.now(SGT)
    today = today or now.strftime("%Y-%m-%d")

    if notion_client is not None:
        from joblander.notion import pull_tracker
        rows = pull_tracker(cfg)          # 晨报前先刷新投影
    else:
        rows = _load_projection(cfg)

    active = [r for r in rows if r.get("Status") in ACTIVE]
    due, overdue = [], []
    for r in active:
        fu = r.get("Follow-up Reminder")
        if not fu:
            continue
        if fu < today:
            overdue.append(r)
        elif fu == today:
            due.append(r)
    pending = _pending_proposals(cfg)

    def _line(r):
        return (f"- **{r.get('Company')}**（{r.get('Status')}｜{r.get('Priority') or '—'}）"
                f"：{r.get('Next Steps') or '—'}")

    md: list[str] = [f"> 生成 {now:%H:%M} ｜ pipeline 活跃 {len(active)}/{len(rows)} 行", ""]
    md += ["### 🔴 逾期 follow-up" if overdue else "### follow-up：无逾期 ✅"]
    md += [_line(r) + f"（挂 {r.get('Follow-up Reminder')}）" for r in overdue]
    if due:
        md += ["", "### 🟡 今日到期"] + [_line(r) for r in due]
    high = [r for r in active if r.get("Priority") == "High"]
    if high:
        md += ["", "### High 优先级战线"] + [_line(r) for r in high]
    if pending:
        md += ["", f"### 待你审批（{len(pending)}）"]
        md += [f"- {p.get('company') or '?'}（`{p['dir']}/{p['file']}`）——UI 各属地页可批"
               for p in pending]

    out = upsert_section(daily_path(cfg, today), MORNING_HEADER,
                         "\n".join(md), title=f"# 日报 · {today}")
    text = out.read_text(encoding="utf-8")
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "daily.generated", "joblander.daily",
        {"date": today, "overdue": len(overdue), "due": len(due), "pending": len(pending)})
    return out, text


def save_notes(cfg, name: str, text: str) -> Path:
    """「我的手记」——日报/周报通用；name 限 13-daily 下的 .md 文件名。"""
    if not re.fullmatch(r"[\w.-]+\.md", name):
        raise ValueError(f"非法文件名：{name}")
    p = cfg.workspace_dir / "13-daily" / name
    title = f"# {'周报' if 'weekly' in name else '日报'} · {name.replace('.md', '')}"
    upsert_section(p, NOTES_HEADER, text.strip(), title=title)
    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "daily.notes_saved", "human_direct", {"file": name, "chars": len(text)})
    return p
