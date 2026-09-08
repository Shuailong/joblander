"""Scribe 金标评分器（F4）—— LLM-as-judge 对照人工参考复盘打分。

指标（DESIGN §7.6）：字段准确率 / 约定遵从（Highlight 一句话）/ 关键信息召回（band·日期·承诺零遗漏）。
用法：python -m evals.scribe_eval           # 评 11-shadow 下全部与金标清单匹配的提案
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from joblander.tz import LOCAL_TZ as SGT   # 单一来源，JOBLANDER_TZ 可覆盖

JUDGE = """你是评测官。对照【参考答案】（人工手写复盘，事实基准）给【系统提案】打分。
评分口径：只按「转写内可得信息」评——参考答案里明显来自外部知识的内容（跨公司换算、打平线等）不计入召回分母。
输出严格 JSON：
{"field_accuracy": 0-5, "convention": 0-5, "recall": 0-5,
 "missed_facts": ["提案漏掉的关键事实（band/日期/承诺/数字）"],
 "wrong_facts": ["提案写错的事实"],
 "verdict": "达标|不达标", "note": "一句话"}
达标线：field_accuracy≥4 且 recall≥4 且无 wrong_facts。"""


def run() -> str:
    from joblander.config import load_config
    from joblander.llm import from_config
    from joblander.prep import _load_projection
    from joblander.scribe import _strip_fences

    cfg = load_config()
    llm = from_config(cfg, "eval")   # 评测裁判永远最强档
    rows = {r.get("Company"): r for r in _load_projection(cfg)}
    shadow_dir = cfg.workspace_dir / "11-shadow"
    now = datetime.now(SGT)
    lines = [f"# Scribe 金标评分 · {now.strftime('%Y-%m-%d %H:%M')}", ""]
    n_pass = n_all = 0

    for f in sorted(shadow_dir.glob("*scribe-shadow.json")):
        proposal = json.loads(f.read_text(encoding="utf-8"))
        if "superseded" in str(proposal.get("reject_reason", "")):
            continue                     # 被新版本替代的旧提案不计入
        company = proposal.get("company")
        ref = (rows.get(company) or {}).get("Feedback")
        if not ref:
            continue
        n_all += 1
        raw = llm.generate(
            f"【参考答案】（人工复盘）：\n{ref}\n\n【系统提案】：\n"
            + json.dumps({k: proposal[k] for k in
                          ("field_diffs", "body_entry", "playbook_updates")},
                         ensure_ascii=False),
            system=JUDGE, json_mode=True)
        r = json.loads(_strip_fences(raw))
        ok = r.get("verdict") == "达标"
        n_pass += ok
        lines += [f"## {f.name}",
                  f"{'✅' if ok else '❌'} 字段 {r.get('field_accuracy')}/5 ｜ 约定 "
                  f"{r.get('convention')}/5 ｜ 召回 {r.get('recall')}/5 — {r.get('note','')}"]
        for m in r.get("missed_facts", []):
            lines.append(f"- 漏：{m}")
        for w in r.get("wrong_facts", []):
            lines.append(f"- ❌ 错：{w}")
        lines.append("")

    lines.insert(1, f"**{n_pass}/{n_all} 达标**（达标线：字段≥4 且召回≥4 且零错误事实）")
    report = "\n".join(lines) + "\n"
    out = cfg.workspace_dir / "16-audits" / f"{now.strftime('%Y-%m-%d-%H%M')}-scribe-eval.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "scribe.evaluated", "evals.scribe_eval", {"passed": n_pass, "total": n_all})
    print(report)
    return str(out)


if __name__ == "__main__":
    run()
