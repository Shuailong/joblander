"""Brief Eval —— 参谋 brief 质量评测（用户金标：10 分钟抓住关键打法）。

hard_checks（零 LLM，用户 2026-08-09 反馈固化为回归线）：
- 全文 ≤4500 字符（10 分钟阅读上限；生成目标更低）
- 不整段罗列：口径卡 / Playbook 原文 / 弹药清单段——这些用户自己有，brief 只指路
- 预判问答 ≤5 条（多了抓不住重点）
- 模板空话禁语
- 内嵌弹药编号必须真实存在（只查弹药库里实际出现过的前缀，避免 R1/P0 误伤）

LLM 评审：user persona 五维——重点清晰度/可执行性/针对性/密度/10 分钟拿到打法。
用法：python -m evals.brief_eval <公司名>   （评 10-briefs 里该公司最新一份）
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone

from joblander.tz import LOCAL_TZ as SGT   # 单一来源，JOBLANDER_TZ 可覆盖

MAX_CHARS = 4500
MAX_QA = 5
BANNED = ("保持自信", "好好准备", "临场发挥", "相信自己", "展现你的热情")
DUMP_SECTIONS = ("## 口径卡", "## Playbook 置顶", "## 弹药点名", "## Pre-flight checklist",
                 "## STAR 弹药索引")

RUBRIC = """评审对象：系统参谋（Prep Agent）为你生成的面前 brief。你面试前只有 10 分钟读它。
按五维打分（各 1-5）：
- focus 重点清晰度：读完能否马上说出本场 3 个关键打法？还是被细节淹没？
- actionable 可执行性：每条打法能不能直接带进面试用？有没有只表态不落地的？
- specificity 针对性：是不是长在这家公司/这段历史上？换家公司还成立的句子都算失分
- density 密度：有没有冗余、重复、可删段落？删掉哪些不损失信息？
- time_to_value：前 1/3 篇幅是否已给出最重要的东西？
输出严格 JSON：
{"scores":{"focus":n,"actionable":n,"specificity":n,"density":n,"time_to_value":n},
 "key_plays_readback":["读完后你复述得出的关键打法——最多 3 条，复述不出就写「复述不出」"],
 "issues":[{"sev":"P0|P1|P2","what":"指向原文的具体问题（引用片段）","fix":"一句话修法"}],
 "praise":["值得保留的点"]}
纪律：issues 最多 6 条；重点检查「太长/罗列/抓不住重点」这类阅读负担问题。"""


def _bank_prefixes(bank: str) -> set[str]:
    return {m[0] for m in re.findall(r"^### (([A-Z]+)\d+)\.", bank, re.M)}


def hard_checks(text: str, bank: str = "") -> list[str]:
    v: list[str] = []
    if len(text) > MAX_CHARS:
        v.append(f"超 10 分钟预算：{len(text)} 字符（上限 {MAX_CHARS}）")
    for s in DUMP_SECTIONS:
        if s in text:
            v.append(f"整段罗列：「{s.lstrip('# ')}」——用户明确不要，brief 只指路")
    qa = text.count("**Q：")
    if qa > MAX_QA:
        v.append(f"预判问答 {qa} 条（>{MAX_QA}，抓不住重点）")
    for b in BANNED:
        if b in text:
            v.append(f"模板空话：「{b}」")
    if bank:
        known = set(re.findall(r"^### ([A-Z]+\d+)\.", bank, re.M))
        prefixes = {re.match(r"[A-Z]+", k).group(0) for k in known}
        cited = set(re.findall(r"\b([A-Z]+\d+)\b", text))
        ghosts = {c for c in cited
                  if re.match(r"[A-Z]+", c).group(0) in prefixes and c not in known}
        if ghosts:
            v.append(f"幻觉弹药编号：{sorted(ghosts)}（弹药库不存在）")
    return v


def run(company: str, name: str = "") -> str:
    from evals.user_agent import PERSONA
    from joblander.config import load_config
    from joblander.llm import from_config
    from joblander.scribe import _strip_fences

    cfg = load_config()
    bdir = cfg.workspace_dir / "10-briefs"
    slug = company.split("（")[0].strip().replace(" ", "-").replace("/", "-")
    if name:
        path = bdir / name
    else:
        cands = sorted(bdir.glob(f"*{slug}*-brief.md"), reverse=True)
        if not cands:
            raise FileNotFoundError(f"10-briefs 里没有 {company} 的 brief")
        path = cands[0]
    text = path.read_text(encoding="utf-8")
    bank_p = cfg.workspace_dir / "03-materials" / "achievement-bank.md"
    bank = bank_p.read_text(encoding="utf-8") if bank_p.exists() else ""

    hard = hard_checks(text, bank)
    llm = from_config(cfg, "eval")
    r = json.loads(_strip_fences(llm.generate(
        f"===== 被评审的 brief（{path.name}）=====\n{text}",
        system=PERSONA + "\n\n" + RUBRIC, json_mode=True)))

    now = datetime.now(SGT)
    s = r.get("scores", {})
    lines = [f"# 参谋 brief 评测 · {company} · {now:%Y-%m-%d %H:%M}",
             f"**{path.name} · {len(text)} 字符** ｜ "
             f"**硬检查：{'通过 ✅' if not hard else f'{len(hard)} 项违规 ❌'}** ｜ "
             + " ｜ ".join(f"{k} {x}/5" for k, x in s.items())
             + f" ｜ 总 {sum(s.values())}/25", ""]
    lines += [f"- [硬检查] {h}" for h in hard]
    kb = r.get("key_plays_readback") or []
    if kb:
        lines += ["", "**读后复述出的关键打法**"] + [f"- {k}" for k in kb]
    for i in r.get("issues", []):
        lines.append(f"- [{i.get('sev')}] {i.get('what')}\n  → {i.get('fix')}")
    lines += [f"- ✅ {p}" for p in r.get("praise", [])]

    report = "\n".join(lines) + "\n"
    out = cfg.workspace_dir / "16-audits" / f"{now:%Y-%m-%d-%H%M}-brief-eval-{slug}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "brief.evaluated", "evals.brief_eval",
        {"company": company, "chars": len(text), "hard_violations": len(hard),
         "total": sum(s.values()), "out": str(out)})
    print(report)
    return str(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("company")
    ap.add_argument("name", nargs="?", default="")
    args = ap.parse_args()
    run(args.company, args.name)
