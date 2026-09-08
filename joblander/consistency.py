"""W16 材料一致性巡检 — 全量对外材料 vs Sentinel 双层。

扫描 workspace 指定目录（简历 md/html、叙事、素材库），每文件过规则层 + 可选判断层，
产出一致性报告。auto 级：只读只报告。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

from joblander.sentinel import Audience, Sentinel

from joblander.tz import LOCAL_TZ as SGT   # 单一来源，JOBLANDER_TZ 可覆盖
DEFAULT_GLOBS = ["03-materials/*.md", "03-materials/*.html", "01-profile/*.md"]


def audit_materials(cfg, llm=None, globs: list[str] | None = None) -> tuple[Path, str]:
    sentinel = Sentinel.from_config(cfg)
    ws = cfg.workspace_dir
    findings_md: list[str] = []
    n_files = n_flagged = 0

    for pattern in (globs or DEFAULT_GLOBS):
        for f in sorted(ws.glob(pattern)):
            n_files += 1
            text = f.read_text(encoding="utf-8", errors="replace")
            verdict = sentinel.check(text, audience=Audience.OUTBOUND)
            entries: list[str] = []
            if verdict.findings:
                entries += [f"  - 规则层 {v.action.value}［{v.rule_id}］命中「{v.excerpt[:60]}」"
                            for v in verdict.findings]
            if llm is not None:
                from joblander.judge import judge
                try:
                    for j in judge(cfg, llm, text[:20000], context_note=f"材料文件 {f.name}"):
                        if j.get("verdict") == "attention":
                            entries.append(f"  - 判断层 ⚠️ {j.get('check','')[:40]}…：{j.get('note','')}")
                except Exception as e:
                    entries.append(f"  - （判断层失败：{e}）")
            if entries:
                n_flagged += 1
                findings_md += [f"### `{f.relative_to(ws)}`"] + entries + [""]

    now = datetime.now(SGT)
    header = [f"# 材料一致性巡检（W16）· {now.strftime('%Y-%m-%d %H:%M')}",
              f"> 扫描 {n_files} 文件，{n_flagged} 个有发现 ｜ auto 级：只报告不修改", ""]
    note = ["（注：素材库/叙事手册含内部备忘性质的红线说明，命中≠事故——人工判断哪些是「对外正文」哪些是「内部注记」。）", ""]
    text = "\n".join(header + note + (findings_md or ["全部通过 ✅"])) + "\n"

    out_dir = ws / "16-audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{now.strftime('%Y-%m-%d')}-materials-audit.md"
    out.write_text(text, encoding="utf-8")
    from joblander.eventlog import EventLog
    EventLog(ws / "08-events" / "event-log.jsonl").append(
        "materials.audited", "joblander.consistency",
        {"files": n_files, "flagged": n_flagged})
    return out, text
