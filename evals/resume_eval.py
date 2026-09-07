"""Resume Eval —— 招聘方视角定制简历评测（盲评 + 教练分拣，信息集分离）。

三步两模型调用（都走 eval 档——评产物的模型不能弱于产产物的）：
- hard_checks：零 LLM——Sentinel 红线复查、量化密度（带数字的战绩 bullet 占比）、联系方式在位
- 招聘方盲评：只见简历文本 + 该司 JD（招聘方的真实信息集，不见弹药库/战况）——
  HR 6 秒初筛 + HM 细读两道关卡，产出 verdict / 逐项 JD 对照 / 弱条目 / 修改建议
- 教练分拣：拿盲评意见 + 弹药库（Agent 的信息集）→ agent_fixable（现有弹药即可执行，
  可直接喂 customise 当修改意见）vs needs_user（弹药库缺的事实，向用户提问——编数字是红线）

评公司定制版时结果回写 meta.resume.versions[].eval，产品 UI 据此渲染行动项。
用法：python -m evals.resume_eval <公司名> [--version resume-v2]
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any

SGT = timezone(timedelta(hours=8))


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.out: list[str] = []; self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"): self.skip += 1
        if tag in ("p", "div", "li", "h1", "h2", "h3", "br", "tr"): self.out.append("\n")
    def handle_endtag(self, tag):
        if tag in ("style", "script"): self.skip -= 1
    def handle_data(self, d):
        if not self.skip: self.out.append(d)


def html_to_text(html: str) -> str:
    p = _Text(); p.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "".join(p.out)).strip()


def hard_checks(cfg, html: str) -> list[str]:
    """零 LLM 硬检查：违规清单（空 = 通过）。生成侧 Sentinel 已拦 block，
    这里复查（母版/外来文件没走生成侧）+ 抓量化密度这类规则写不了的质量信号。"""
    from joblander.sentinel import Sentinel

    v: list[str] = []
    verdict = Sentinel.from_config(cfg).check(html)
    if verdict.action.value != "pass":
        v.append(f"Sentinel {verdict.action.value}：{verdict.explain()[:120]}")
    text = html_to_text(html)
    if "@" not in text:
        v.append("联系方式缺失：全文没有邮箱")
    lis = [html_to_text(m) for m in re.findall(r"<li[^>]*>(.*?)</li>", html, re.S)]
    lis = [x for x in lis if len(x) > 24]                  # 只算战绩型 bullet，跳过技能词条（CJK 战绩句偏短）
    if lis:
        with_num = sum(1 for x in lis if re.search(r"\d", x))
        if with_num / len(lis) < 0.5:
            v.append(f"量化密度低：{len(lis)} 条战绩 bullet 仅 {with_num} 条带数字")
    return v


def _pdf_pages(pdf_bytes: bytes) -> int:
    """零依赖页数：页树 /Count（Chrome 产 PDF 未压缩可读），退回数 /Type /Page 对象。"""
    counts = [int(m) for m in re.findall(rb"/Count\s+(\d+)", pdf_bytes)]
    return max(counts) if counts else len(re.findall(rb"/Type\s*/Page\b", pdf_bytes))


def format_checks(cfg, html: str, *, pdf_path=None) -> list[str]:
    """格式硬检查（零 LLM，Agent 可修）：页数守约。样式版式代码渲染，不再需要跟母版比对。"""
    v: list[str] = []
    if pdf_path is not None and pdf_path.exists():
        pages = _pdf_pages(pdf_path.read_bytes())
        if pages > 2:
            v.append(f"格式：PDF 渲染 {pages} 页，超过 2 页上限——压缩与 JD 弱相关的条目")
    return v


RECRUITER_SYSTEM = """你在扮演目标公司的两个真实招聘方角色，先后评一份收到的简历。
你只看得到这份简历和本司 JD——没有内推背书、没有面试印象，纸面就是全部。
（公司与岗位背景以 JD 为准；JD 没写的不要脑补。）

角色 1【HR/猎头初筛，6 秒 + 60 秒】：扫描视角。title 对齐、年限、地点与到岗、
公司品牌、任期红旗、关键词命中。给 screen_pass: yes|borderline|no。

角色 2【Hiring Manager 细读，5 分钟】：工程视角。逐条战绩挑证据成色——数字是「我做的」
还是「团队的」？与 JD 要求逐项对照。给 hm_read: strong_yes|yes|borderline|no。

输出严格 JSON：
{"screen": {"pass": "...", "flags": ["让初筛犹豫的点"]},
 "hm": {"read": "...",
  "jd_fit": [{"req": "JD 要求", "evidence": "简历上的证据或『纸面无证据』", "grade": "strong|ok|weak|missing"}],
  "probes": ["面试会追问的具体问题，3-5 个，含刁钻的"],
  "weak_bullets": [{"quote": "简历原文", "why": "为什么弱（空话/无数字/看不出本人贡献/与 JD 无关）"}]},
 "verdict": {"interview": "yes|no", "one_line": "一句话总评",
  "top_fixes": ["按影响力排序的 3-5 条具体修改建议——指到具体条目，给改法"]}}
纪律：引用必须来自简历原文；不许脑补简历没写的经历；夸和批都要指到具体行。"""

COACH_SYSTEM = """你是简历教练，负责把招聘方的评估意见变成可执行的行动。你手里有：
招聘方意见（JSON）+ 候选人弹药库全文（战绩事实的唯一来源）。

把每条意见分拣进两个桶：
- agent_fixable：弹药库里**已有**所需事实/数字，改写简历即可落实——写成给简历定制 Agent 的
  精确指令（指到具体条目，说清怎么改、用弹药库哪条素材）
- needs_user：弹药库里**没有**所需事实（缺基线、缺数字、缺技术细节）——写成向候选人要事实的
  具体问题。绝不允许建议编造或放大。

输出严格 JSON：
{"agent_fixable": ["给定制 Agent 的修改指令，一条一个动作"],
 "needs_user": [{"q": "建议候选人补充的信息——点名条目和指标方向（如规模/延迟/归因/成本），
   但不预设格式：候选人手里的可能是别的更有力的事实", "why": "补哪条弱点"}]}
纪律：先**逐段通读弹药库再分桶**——文末「补充素材」段与公司无关、对任何战役全部适用，
文中任何段落已有的信息（哪怕表述粗糙）都算「库里有」：粗糙的库内事实归 agent_fixable
（指挥 Agent 改写进简历），**绝不能再向用户要一遍**；needs_user 每条先自问
「弹药库哪一段找过了、为什么不算有」，答不上就不许列。库里没有的也不许让 Agent 硬写。
agent_fixable 只列真正影响面试判定的修改，没有就输出空数组——不为凑数找茬（这是循环的收敛条件）。
若输入含【上一轮意见】：先逐条裁定落实情况——已落实的不再列；只列仍未落实的和本版新引入的
问题，不许换个说法重提同一条，也不许每轮开辟新战场（宁可空数组，不可漂移）。
若输入含【已问过用户的补料问题】：这些一条都不许再列——用户看到过、选择未回应，重复提问
是噪音；同义改写也算重复。needs_user 只放真正**新**的缺口，没有就空数组。
你的指令不得稀释量化密度：拆分/新增条目若无数字支撑，选择合并或压缩而不是铺开。
各桶最多 5 条，按影响力排序。"""


def run(cfg, company: str, version: str = "",
        prev_fixable: list[str] | None = None) -> dict[str, Any]:
    from joblander import company as companyfile
    from joblander.eventlog import EventLog
    from joblander.llm import from_config
    from joblander.resume_agent import resume_dir, resume_state
    from joblander.scribe import _strip_fences

    state = resume_state(cfg, company)
    ver_file = version or state.get("current") or ""
    if ver_file:
        html_p = resume_dir(cfg, company) / f"{ver_file}.html"
        label = ver_file
        fmt = format_checks(cfg, html_p.read_text(encoding="utf-8"),
                            pdf_path=html_p.with_suffix(".pdf"))
    else:                                   # 无定制版 → 评母版（招聘方此刻拿到的就是它）
        html_p = cfg.workspace_dir / "03-materials" / "resume.html"
        label = "母版"
        fmt = []                            # 母版即基准，样式/页数不自证
    html = html_p.read_text(encoding="utf-8")
    jd = companyfile.jd_text(cfg, company)

    hard = hard_checks(cfg, html) + fmt
    llm = from_config(cfg, "eval")
    resume_txt = html_to_text(html)
    # 没有 JD 时必须说清楚「本次没有 JD」，否则裁判会自行想象一份 JD，
    # 再产出「HM 逐项对照 JD」的九条比对，读者会当成这家公司真实要求。
    jd_block = (f"【本司 JD】\n{jd[:12000]}" if jd else
                "【本司 JD】（本次没有 JD 原文）\n"
                "纪律：不得虚构 JD 条目，不得输出任何逐项对照；"
                "jd_fit 一律给空数组，只按简历自身质量评。")
    recruiter = json.loads(_strip_fences(llm.generate(
        f"{jd_block}\n\n【收到的简历（全文文本）】\n{resume_txt[:12000]}",
        system=RECRUITER_SYSTEM, json_mode=True)))
    if not jd:                      # 代码侧兜底：模型不听话也不让对照上报告
        recruiter.setdefault("hm", {})["jd_fit"] = []

    bank_p = cfg.workspace_dir / "03-materials" / "achievement-bank.md"
    bank = bank_p.read_text(encoding="utf-8") if bank_p.exists() else ""
    prev_block = ("\n\n【上一轮意见（先逐条裁定落实情况，已落实的不再列）】\n"
                  + "\n".join(f"- {x}" for x in prev_fixable)) if prev_fixable else ""
    asked = [str(a.get("q") or "").strip() for a in state.get("asked_user") or []]
    asked_block = ("\n\n【已问过用户的补料问题（未回应≠再问一遍——一条都不许重复，"
                   "同义改写也算）】\n" + "\n".join(f"- {q}" for q in asked if q)) \
        if asked else ""
    coach = json.loads(_strip_fences(llm.generate(
        f"【招聘方意见】\n{json.dumps(recruiter, ensure_ascii=False)}\n\n"
        f"【弹药库全文】\n{bank[:60000]}" + prev_block + asked_block,   # 截尾会先丢文末红线段
        system=COACH_SYSTEM, json_mode=True)))
    askset = {q for q in asked if q}            # 代码侧兜底：模型漏守时精确匹配再滤一道
    raw_needs = coach.get("needs_user") or []
    coach["needs_user"] = [x for x in raw_needs
                           if str(x.get("q") or "").strip()
                           and str(x.get("q") or "").strip() not in askset]
    dropped_needs = len(raw_needs) - len(coach["needs_user"])

    now = datetime.now(SGT)
    s, h, v = recruiter.get("screen", {}), recruiter.get("hm", {}), recruiter.get("verdict", {})
    lines = [f"# 招聘方视角简历评测 · {company} · {label} · {now:%Y-%m-%d %H:%M}",
             "> 盲评信息集 = 简历 + JD（无弹药库/战况）；教练分拣持弹药库。文本评估，版式不裁。",
             "",
             f"**硬检查：{'通过 ✅' if not hard else f'{len(hard)} 项 ❌'} ｜ "
             f"初筛 {s.get('pass')} ｜ HM {h.get('read')} ｜ 邀约 {v.get('interview')}** — {v.get('one_line')}", ""]
    lines += [f"- [硬检查] {x}" for x in hard]
    lines.append("\n## HM 逐项对照 JD")
    lines += [f"- [{x.get('grade')}] {x.get('req')} ← {x.get('evidence')}" for x in h.get("jd_fit", [])]
    lines.append("\n## 初筛犹豫点")
    lines += [f"- {x}" for x in s.get("flags", [])]
    lines.append("\n## 面试必追问")
    lines += [f"- {x}" for x in h.get("probes", [])]
    lines.append("\n## 弱条目")
    lines += [f"- 「{x.get('quote')}」— {x.get('why')}" for x in h.get("weak_bullets", [])]
    lines.append("\n## 修改建议（按影响力）")
    lines += [f"{i + 1}. {x}" for i, x in enumerate(v.get("top_fixes", []))]
    lines.append("\n## 教练分拣 → Agent 可直接执行")
    lines += [f"- {x}" for x in coach.get("agent_fixable", [])]
    lines.append("\n## 教练分拣 → 建议用户补充的信息（只列新问题）")
    lines += [f"- {x.get('q')}（补：{x.get('why')}）" for x in coach.get("needs_user", [])]
    if dropped_needs:
        lines.append(f"- （另有 {dropped_needs} 条此前问过、未回应——不再重复提）")

    slug = company.split("（")[0].strip().replace(" ", "-").replace("/", "-")[:40]
    out = cfg.workspace_dir / "16-audits" / f"{now:%Y-%m-%d-%H%M}-resume-eval-{slug}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = {"label": label, "hard": hard, "recruiter": recruiter, "coach": coach,
              "report": str(out)}
    if ver_file:                            # 定制版 → 回写版本条目，产品 UI 据此渲染
        from joblander.company import save_meta
        surfaced = (coach.get("needs_user") or [])[:5]
        for entry in state.get("versions") or []:
            if entry.get("file") == ver_file:
                entry["eval"] = {
                    "at": now.strftime("%Y-%m-%d %H:%M"),
                    "screen": s.get("pass"), "hm": h.get("read"),
                    "interview": v.get("interview"), "one_line": v.get("one_line"),
                    "hard": hard, "top_fixes": (v.get("top_fixes") or [])[:5],
                    "agent_fixable": (coach.get("agent_fixable") or [])[:5],
                    "needs_user": surfaced,
                    "report": out.name}
        # 问过即记账：下版评审不再重提（用户回应=事实进弹药库，问题自然消失）
        state["asked_user"] = ((state.get("asked_user") or [])
                               + [{"q": str(x.get("q") or "").strip(), "file": ver_file,
                                   "at": now.strftime("%Y-%m-%d")}
                                  for x in surfaced if str(x.get("q") or "").strip()])[-40:]
        save_meta(cfg, company, {"resume": state})

    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "resume.evaluated", "evals.resume_eval",
        {"company": company, "version": label, "hard_violations": len(hard),
         "interview": v.get("interview"), "out": str(out)})
    return result


if __name__ == "__main__":
    from joblander.config import load_config

    ap = argparse.ArgumentParser()
    ap.add_argument("company")
    ap.add_argument("--version", default="")
    a = ap.parse_args()
    r = run(load_config(), a.company, version=a.version)
    print(r["report"])
