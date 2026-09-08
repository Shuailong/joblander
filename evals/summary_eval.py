"""Summary Eval —— 尽调员「公司综合简介」质量评测（User Agent 方法论）。

两层：
- hard_checks：程序化硬检查（零 LLM，可单测、可回归）——四段结构/薪酬信号必现/
  禁语句式/通用风险凑数/来源分级覆盖。改 SYNTH_SYSTEM 后这层先兜底。
- LLM 评审：复用 user_agent 人设 + 五维量规（决策有用性/事实与来源/关切覆盖/
  可核查性/表达效率），报告落 workspace/16-audits/。

用法：python -m evals.summary_eval <公司名>   （评 workspace 里现存 dossier）
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone

from joblander.tz import LOCAL_TZ as SGT   # 单一来源，JOBLANDER_TZ 可覆盖

REQUIRED_SECTIONS = ("这家公司是谁", "为什么现在招这个岗", "工程与技术侧", "对你意味着什么")
BANNED_PHRASES = (r"适合对.{0,14}感兴趣", r"提供了?.{0,10}(良好的?)?(机会|平台)")
PROMPT_LEAK = ("综合简介 markdown", "固定四段", "上述四段", "每段以粗体小标题")
CONTEXT_LEAK = ("[用户输入]",)
GENERIC_RISKS = (r"市场波动", r"技术(能力|要求)", r"快速变化", r"竞争激烈")

RUBRIC = """评审对象：系统尽调员（Diligence Agent）自动生成的「公司综合简介」（给求职者面前/投前读）。
按五维打分（各 1-5）：
- decision_value 决策有用性：读完能否回答「该不该投入这家、面试该怎么打」？有没有 so-what？
- evidence 事实与来源：断言是否具体（数字/日期/口径）？编号引用是否可信？高价值信号有没有漏挖？
- coverage 求职者关切覆盖：业务与稳定性/该岗位为什么开/工程与技术栈/团队与文化/薪酬信号/面试流程，覆盖几样？
- verifiability 可核查性：来源质量分层是否交代？摘要与全文的区别读者是否知情？
- efficiency 表达效率：30 秒能读完抓住重点吗？有没有空话占位？
输出严格 JSON：
{"scores":{"decision_value":n,"evidence":n,"coverage":n,"verifiability":n,"efficiency":n},
 "issues":[{"sev":"P0|P1|P2","what":"指向文本里真实存在/缺失的具体问题（引用原文片段）","fix":"一句话修法"}],
 "praise":["值得保留的点"]}
纪律：issues 最多 8 条；特别检查 dossier 里已抓到但简介没用上的信号。"""


def hard_checks(dossier: dict) -> list[str]:
    """零 LLM 硬检查：违规清单（空 = 通过）。改 prompt 后的第一道回归。"""
    v: list[str] = []
    md = dossier.get("summary_md") or ""
    for h in REQUIRED_SECTIONS:
        if h not in md:
            v.append(f"缺段落：**{h}**")
    # 薪酬信号：正文按岗位相关性筛选是合法的（防聚合数字刷屏），但不许全军覆没
    sigs = [s for s in dossier.get("salary_signals") or []
            if re.findall(r"\$?[\d][\d,.]*\s*[kK万亿]?", s)]
    if sigs and not any(n.strip() in md for s in sigs
                        for n in re.findall(r"\$?[\d][\d,.]*\s*[kK万亿]?", s)):
        v.append(f"薪酬信号一条都没进简介（archive 有 {len(sigs)} 条）")
    for pat in BANNED_PHRASES:
        if re.search(pat, md):
            v.append(f"空话句式命中：/{pat}/")
    for r in dossier.get("risks") or []:
        if any(re.search(g, r) for g in GENERIC_RISKS) and len(r) < 40:
            v.append(f"通用风险凑数：{r[:36]}")
    srcs = dossier.get("sources") or []
    if dossier.get("mode") == "deep" and srcs and not all(s.get("tier") for s in srcs):
        v.append("sources 缺 tier 分级")
    if dossier.get("mode") == "deep":              # 30 秒要点卡：裁判跨样本共识的摘要层
        card = [str(c).strip() for c in dossier.get("card") or [] if str(c).strip()]
        if not card:
            v.append("缺 30 秒要点卡（card）")
        elif len(card) > 5:
            v.append(f"要点卡超长：{len(card)} 行（≤5）")
        for pat in BANNED_PHRASES:
            if any(re.search(pat, c) for c in card):
                v.append(f"要点卡空话句式：/{pat}/")
    if not re.search(r"\[\d+\]", md):
        v.append("简介无任何编号引用")
    head = md[:200]
    for leak in PROMPT_LEAK:
        if leak in head:
            v.append(f"prompt 指令泄漏进正文：「{leak}」")
    for leak in CONTEXT_LEAK:
        if leak in md:
            v.append(f"战况引用格式违规：「{leak}」（应写「（你的战况）」）")
    return v


def run(company: str) -> str:
    from evals.user_agent import PERSONA
    from joblander.config import load_config
    from joblander.llm import from_config
    from joblander.scribe import _strip_fences

    cfg = load_config()
    from joblander.company import dossier_path
    dp = dossier_path(cfg, company)
    slug = dp.stem                    # 报告文件名用它——档案路径已是规范 slug
    dossier = json.loads(dp.read_text(encoding="utf-8"))

    hard = hard_checks(dossier)

    llm = from_config(cfg, "eval")   # 评测裁判永远最强档
    payload = (f"===== 被评审的简介 =====\n{dossier.get('summary_md')}\n\n"
               f"===== dossier 其余字段（检查「抓到了但没用上」）=====\n"
               f"facts: {json.dumps(dossier.get('facts'), ensure_ascii=False)}\n"
               f"salary_signals: {json.dumps(dossier.get('salary_signals'), ensure_ascii=False)}\n"
               f"risks: {json.dumps(dossier.get('risks'), ensure_ascii=False)}\n"
               f"gaps: {json.dumps(dossier.get('gaps'), ensure_ascii=False)}\n"
               f"sources: {json.dumps(dossier.get('sources'), ensure_ascii=False)}")
    r = json.loads(_strip_fences(llm.generate(
        payload, system=PERSONA + "\n\n" + RUBRIC, json_mode=True)))

    now = datetime.now(SGT)
    s = r.get("scores", {})
    lines = [f"# 尽调简介评测 · {company} · {now:%Y-%m-%d %H:%M}",
             f"**硬检查：{'通过 ✅' if not hard else f'{len(hard)} 项违规 ❌'}** ｜ "
             + " ｜ ".join(f"{k} {v}/5" for k, v in s.items())
             + f" ｜ 总 {sum(s.values())}/25", ""]
    for h in hard:
        lines.append(f"- [硬检查] {h}")
    for i in r.get("issues", []):
        lines.append(f"- [{i.get('sev')}] {i.get('what')}\n  → {i.get('fix')}")
    for p in r.get("praise", []):
        lines.append(f"- ✅ {p}")

    report = "\n".join(lines) + "\n"
    out = cfg.workspace_dir / "16-audits" / f"{now:%Y-%m-%d-%H%M}-summary-eval-{slug}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "summary.evaluated", "evals.summary_eval",
        {"company": company, "hard_violations": len(hard),
         "total": sum(s.values()), "out": str(out)})
    print(report)
    return str(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("company")
    run(ap.parse_args().company)
