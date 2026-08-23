"""Prep 参谋 — W7/W5 战役策略 + 面前参谋（v1：LLM 参谋核心 + 确定性守卫层）。

v0（零 LLM 模板拼装）的教训：通用打法不看这家公司实际发生过什么，没法用。
v1 三层：
- 确定性战况头：tracker 行的事实字段，不需要判断
- LLM 参谋核心：吃全部战况（事件时间线、JD、尽调档案、评估匹配、弹药库、playbook、
  投出的简历版本、下一轮信息）→ 战役层策略 + 下一轮打法 + 预判问答 + 弹药点名 + 必问
- 确定性守卫尾：口径卡（Sentinel 规则）、playbook needs_work 标准答案原文、
  pre-flight checklist——红线与背诵原文由代码原样附上，LLM 无权改写
产出受 evals/brief_eval 金标约束（用户 2026-08-09 反馈）：10 分钟读完、
关键打法置顶、不整段罗列弹药/口径/playbook——只指路。配额代码侧硬截断。
LLM 掉线降级为轮次模板骨架，brief 永远出得来。

2026-08-10 校准（用户反馈「浮于表面」）：篇幅不放、深度补回——
reasoning effort 拉 high（思考不占篇幅），产出体裁从「目录指路」改「结论+因果链」，
预判答法必须自含可开口的说法，不许只写书签。

2026-08-13 校准（用户反馈「内容不太有用，没体现出战略」）：v1 逐条硬塞弹药编号的写法
把 brief 写成了背诵稿，局面判断被本轮话术清淹没。改为局面判断 + 接下来的打法为主轴，
判断依据优先取最近时间线上的复盘/附件/对方反馈（真正变化在哪），弹药与红线/playbook
引用降级为「需要时才引用」，不再逐条强制配数字。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import yaml

SGT = timezone(timedelta(hours=8))


def _load_projection(cfg) -> list[dict[str, Any]]:
    path = cfg.workspace_dir / "09-projections" / "tracker.json"
    if not path.exists():
        raise FileNotFoundError(f"投影不存在：{path}（先跑 python -m joblander pull）")
    with open(path, encoding="utf-8") as f:
        return json.load(f)["rows"]


def find_row(rows: list[dict], company_query: str) -> dict[str, Any]:
    q = company_query.casefold()
    exact = [r for r in rows if (r.get("Company") or "").casefold() == q]
    if exact:
        return exact[0]
    partial = [r for r in rows if q in (r.get("Company") or "").casefold()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise LookupError(f"tracker 无匹配公司：{company_query}")
    names = [r["Company"] for r in partial]
    raise LookupError(f"匹配到多行：{names}，请给更精确的名字")


def _load_playbook(cfg) -> list[dict[str, Any]]:
    path = cfg.workspace_dir / "03-materials" / "playbook.yaml"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


ROUND_TEMPLATES: dict[str, dict[str, Any]] = {
    "screening": {
        "label": "Screening · HR/猎头初筛",
        "play": ["- 目标是过门 + 摸信息，不是赢面试——答案短，留在对方节奏里",
                 "- 薪酬只报总包口径（见口径卡），绝不先报拆解数字",
                 "- 离职原因用标准 30 秒版本，不展开、不辩解"],
        "asks": ["- band/档位对应的**数字区间**（P8：title 不可比，只比数字）",
                 "- 完整流程：几轮、什么形式、时间线多长",
                 "- 岗位空缺原因（新增 or 补位）"],
        "probe": "screening 初筛 薪酬 流程 hr",
    },
    "oa": {
        "label": "笔试 / OA",
        "play": ["- 先扫全卷再动手：按 分值×把握 排序做，不按题号死磕",
                 "- 限时题先交能跑的朴素解再优化——0 分和 60 分差在有没有提交",
                 "- take-home 按真项目交付：README + 测试 + trade-off 说明，评的是工程素养"],
        "asks": ["- 评分维度与通过线（能问就问）", "- 结果反馈时间与下一轮衔接"],
        "probe": "coding algorithm 算法 数据结构 sql python 工程",
    },
    "tech": {
        "label": "技术轮",
        "play": ["- 先复述题目与约束再动手；讲 trade-off 比讲答案值钱",
                 "- 系统设计从需求量级问起，别上来画框",
                 "- 不会就说清思路边界，不虚构——对方存转写，跨场次一致性是硬约束"],
        "asks": ["- 团队技术栈与当前最痛的技术问题",
                 "- 这个岗位进来第一个季度做什么"],
        "probe": "系统 架构 llm agent rag eval coding design 算法",
    },
    "hm": {
        "label": "Hiring Manager 轮",
        "play": ["- 多问「这个岗位为什么现在开」——对齐真实痛点",
                 "- 战绩讲 impact 链路（问题→动作→数字），⭐ 弹药优先",
                 "- 主动给 30/60/90 天打法，展示 ownership"],
        "asks": ["- 团队构成与汇报线", "- 成功标准：半年后怎么算做得好",
                 "- 下一轮形式与时间线"],
        "probe": "团队 交付 impact roadmap ownership 项目",
    },
    "bar": {
        "label": "Bar Raiser / 交叉面",
        "play": ["- 对方可能不懂你的领域——把问题本身讲清楚比堆术语重要",
                 "- 行为面按 STAR 走：每个故事一个冲突点 + 一个数字",
                 "- 与此前轮次口径完全对齐（见全史）——跨场次一致性最要命"],
        "asks": ["- 这一轮的评估维度是什么"],
        "probe": "behavioral star 协作 冲突 失败 复盘",
    },
    "negotiation": {
        "label": "谈判轮",
        "play": ["- 先分清阶段：定级/offer 还没拍板（仍在 HC 或对齐审核）是「游说定级」，"
                 "战绩数字这时还有用；对方已确定要发 offer、开始谈数字，就是「真议价」，"
                 "战绩已经完成任务，这时候复述简历是筹码不足的信号，别再引用",
                 "- 真议价阶段：先听 offer 全貌再回应，当场不给承诺",
                 "- 只用总包口径对话；对方先给数字，再谈结构",
                 "- 每个让步换一个东西（签字费 / 到岗时间 / 评审周期）——"
                 "真正的筹码是市场对标、其他 offer、期限，不是战绩"],
        "asks": ["- offer 全结构：base/bonus/equity 与归属节奏",
                 "- 答复截止时间"],
        "probe": "offer 谈判 base bonus equity 总包",
    },
}

_ROUND_HINTS = [("oa", ("笔试", "take-home", "take home", "hackerrank", "codility",
                        "online assessment", "测评")),   # 不放裸 "oa"：子串会误中 roadmap/goal
                ("screening", ("screen", "hr", "recruiter", "初筛", "phone")),
                ("tech", ("tech", "coding", "system design", "技术", "algorithm", "白板")),
                ("hm", ("hiring manager", "hm", "manager", "主管", "总监", "lead")),
                ("bar", ("bar raiser", "bar-raiser", "cross", "交叉")),
                ("negotiation", ("offer", "negoti", "谈判", "package"))]


def guess_round(title: str) -> str:
    """日历/事件标题 → 轮次类型；猜不中返回空串（通用模板）。"""
    low = (title or "").casefold()
    return next((rt for rt, kws in _ROUND_HINTS if any(k in low for k in kws)), "")


PREP_SYSTEM = """你是求职作战系统的参谋（Prep Agent）。输入对某公司战役的全部战况材料，
输出一份**判断当前局面、给出接下来打法**的战役级 brief——目的是让人看完立刻知道
「现在什么状况、下一步该干什么」，不是一份逐句要背的面试话术稿。

预算（硬约束）：全部字段合计 ≤1000 字——宁缺毋滥，砍到只剩真正影响判断的。
strategy ≤5 条（每条 ≤90 字）、qa_prep ≤3（答法 ≤70 字）、asks ≤3、watchouts ≤3。
不罗列弹药清单/口径原文/playbook 原文——用户自己有，只在真正需要时点名引用。

判断依据优先级（这是本次校准的核心——用户 2026-08-13 反馈「没体现出战略」）：
1. 最近时间线上的复盘、附件、对方反馈——上一轮到底发生了什么、暴露了什么、
   跟上次 brief 相比局面有没有变化，这是局面判断的主要依据，不是背景装饰
2. JD 与尽调红旗——用来判断这家公司/这个岗位真正的博弈点在哪
3. 弹药库/playbook——只在打法里确实需要一个具体数字或战绩支撑论点时才引用，
   不必每条都塞编号；能用一句话讲清楚战略判断，不需要就不引

深度（压缩的是字数，不是思考）：
- 先在心里把这场战役重新推演一遍：形势相比上次有什么变化、我方现在的筹码和风险是什么、
  接下来几步棋该怎么走——想透了再压缩成产出，不是罗列话术清单
- strategy 是战役层面的下一步（这周该做什么、要不要调整节奏或说法、
  有没有需要提前准备的材料），不是本轮逐句要背的台词；
  每条=判断+为什么，「保持自信」「好好准备」这类模板话不许出现
- 通用正确但换家公司也成立的话，等于没写——每个字都要长在这家公司的战况上

纪律：
- 弹药库战绩的作用是「证明你值这个价」，只在对方还没决定要不要用你/给什么级的阶段有效
  （screening 到 bar 各轮，或定级/offer 还没拍板、仍要靠证据游说的窗口）。
  一旦对方已经认可、进入真正谈数字/条件的阶段，战绩不再是筹码——这时候管用的是
  市场对标、其他 offer、期限压力、非货币条件；复述简历数字是准备不足的信号，别再引用
- 一切判断从材料出发，尤其是时间线里真实发生的事（带日期）；材料没有的不编造；
  已确认事实、对方口述、你的推断三者措辞分清，别把推断写成定论
- 预判问题优先从三处推导：①上轮面试/复盘暴露的弱点 ②JD 与弹药的差距 ③尽调红旗；
  只在有明确下一轮时才给 qa_prep，答法要能直接开口说，不是书签
- 该问对方的问题优先从尽调「未查到」清单取，按优先级只留最值得问的
- 指定轮次与战况不符时（如还没投递就要技术轮 brief），watchouts 第一条点破，
  打法照出但按「提前备战」措辞
- 薪酬口径、离职叙事等红线内容不改写、不展开，只写「按口径」——原文在 /system 页
- 中文输出，专名保留原文

输出严格 JSON：
{"situation": "局面 3-4 句：最近发生了什么（引用时间线/复盘里的具体事，带日期）、
  跟上次相比有没有变化、主动权在谁、当前最大的不确定性是什么",
 "strategy": ["接下来的打法 3-5 条，战役层面：下一步做什么、为什么——
  需要具体数字/战绩支撑时才引用，不必每条都引"],
 "watchouts": ["当前最该警惕的风险 ≤3 条，优先来自最近复盘/时间线暴露的问题"],
 "qa_prep": [{"q": "若有明确下一轮，预判最可能被问到的问题", "a": "≤70 字可开口答法"}],
 "asks": ["该问对方的问题，≤3（无信息缺口可留空数组）"]}"""

_KIND_LABEL = {"interview": "面试", "call": "通话", "email": "邮件", "note": "笔记",
               "retro": "复盘", "assessment": "评估", "intake": "入池", "transcript": "转写"}
_RICH_KINDS = ("interview", "oa", "retro", "call", "assessment")


def _dossier(cfg, company: str) -> dict[str, Any]:
    slug = company.split("（")[0].strip().replace(" ", "-").replace("/", "-")[:40]
    p = cfg.workspace_dir / "14-dossiers" / f"{slug}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def _timeline_digest(cfg, company: str, cap: int = 18000) -> str:
    """事件列表 → 旧→新叙事摘录。近的事优先保全：从新往旧装，装满为止再倒回时序。
    只读本地档案（2026-08-10 起 Notion 不做内容同步）。"""
    from joblander.company import merged_timeline
    try:
        entries = merged_timeline(cfg, company)   # 新在前
    except Exception:
        entries = []
    picked, used = [], 0
    for e in entries:
        rich = e.get("kind") in _RICH_KINDS
        content = (e.get("content_md") or "").strip()[:1200 if rich else 300]
        block = (f"- {e.get('date')} [{_KIND_LABEL.get(e.get('kind'), e.get('kind'))}] "
                 f"{e.get('title')}"
                 + (f"（{e.get('summary')}）" if e.get("summary") else "")
                 + (f"\n  {content}" if content else ""))
        if used + len(block) > cap:
            break
        picked.append(block)
        used += len(block)
    return "\n".join(reversed(picked)) or "（时间线为空）"


def _bank_text(cfg) -> str:
    p = cfg.workspace_dir / "03-materials" / "achievement-bank.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _context_pack(cfg, row, company: str, *, round_type: str, round_note: str,
                  jd: str = "") -> str:
    from joblander.company import load_meta

    rt = ROUND_TEMPLATES.get(round_type)
    meta = load_meta(cfg, company)
    dossier = _dossier(cfg, company)
    assessment = meta.get("assessment") or {}

    status = "\n".join(f"- {k}：{row.get(k) or '—'}" for k in
                       ("Position", "Status", "Priority", "Source", "Contact Person",
                        "Next Steps", "Follow-up Reminder", "Highlight", "Feedback"))
    nxt = [f"轮次类型：{rt['label'] if rt else '未指定（通用）'}"]
    if round_note:
        nxt.append(f"本场备注：{round_note}")
    if rt:
        nxt.append("轮次通用基线（需结合本公司具体化，别照抄）：\n"
                   + "\n".join(rt["play"] + rt["asks"]))

    dos = "（无尽调档案）"
    if dossier:
        dos = "\n".join(filter(None, [
            "要点卡：" + "；".join(dossier.get("card") or []) if dossier.get("card") else "",
            (dossier.get("summary_md") or "")[:4000],
            "红旗：" + "；".join(dossier.get("risks") or []) if dossier.get("risks") else "",
            "未查到（面试可问）：\n" + "\n".join(f"- {g}" for g in dossier.get("gaps") or [])
            if dossier.get("gaps") else ""]))

    hot = [p for p in _load_playbook(cfg) if p.get("status") in ("needs_work", "improving")]
    pb = "\n".join(f"- {p['id']} {p.get('pattern')}（{p.get('status')}）："
                   f"{(p.get('best_answer') or '')[:300]}" for p in hot) or "（无）"

    return "\n\n".join([
        f"【公司】{company}",
        f"【战况（tracker）】\n{status}",
        f"【投出的简历版本】{meta.get('resume_variant') or '未记录'}",
        "【下一轮】\n" + "\n".join(nxt),
        f"【事件时间线（旧→新）】\n{_timeline_digest(cfg, company)}",
        f"【JD 原文】\n{jd[:6000] if jd else '（无 JD——提醒用户先要 JD）'}",
        f"【尽调档案】\n{dos}",
        f"【评估匹配】\n{json.dumps(assessment, ensure_ascii=False)[:2500] if assessment else '（未评估）'}",
        f"【Playbook 战况（needs_work/improving）】\n{pb}",
        f"【弹药库全文】\n{_bank_text(cfg)[:40000]}",
    ])


def _staff_sections(out: dict[str, Any], rt) -> list[str]:
    """LLM 参谋产出 → markdown 段。配额代码侧硬执行（超发直接截断）——
    局面 + 打法为主轴，10 分钟金标不靠模型自觉。"""
    def _clean(s: str) -> str:                  # 剥 prompt 回声：行首 ⚡/序号/多余空白
        return re.sub(r"^[⚡①-⑩\s]+", "", str(s)).strip()

    md: list[str] = ["", "## 局面", (out.get("situation") or "").strip()]
    md += ["", f"## 接下来的打法{'（' + rt['label'] + '在即）' if rt else ''}"]
    md += [f"{i}. {_clean(p)}" for i, p in enumerate((out.get("strategy") or [])[:5], 1)]
    if out.get("watchouts"):
        md += ["", "## 易翻车点"] + [f"- {w}" for w in out["watchouts"][:3]]
    qa = (out.get("qa_prep") or [])[:3]
    if qa:
        md += ["", "## 预判问答"]
        for x in qa:
            md += [f"- **Q：{x.get('q', '')}**", f"  → {x.get('a', '')}"]
    if out.get("asks"):
        md += ["", "## 本场必问"] + [f"- {a}" for a in out["asks"][:3]]
    return md


def _fallback_sections(cfg, row, rt, round_type: str, jd: str = "") -> list[str]:
    """降级骨架：轮次通用模板（同样遵守 10 分钟金标——不罗列弹药库）。"""
    md: list[str] = []
    if rt:
        md += ["", f"## 本轮打法（{rt['label']}·通用模板）"] + rt["play"]
    md += ["", "## 本场必问"]
    if not (row.get("Job URL") or jd):
        md.append("- 要 JD 原文（P6 教训：没有 JD 不投入准备）")
    md += rt["asks"] if rt else ["- band/档位对应的**数字区间**（P8：title 不可比，只比数字）",
                                 "- 下一轮形式与时间线"]
    return md


def build_brief(cfg, llm, company_query: str, *, round_note: str = "",
                round_type: str = "") -> tuple[Path, str]:
    """生成参谋 brief → <workspace>/10-briefs/。返回 (路径, markdown)。
    round_type ∈ ROUND_TEMPLATES；LLM 失败自动降级为模板骨架版（守卫尾两版都在）。"""
    from joblander.scribe import _strip_fences

    from joblander.company import jd_text

    rows = _load_projection(cfg)
    row = find_row(rows, company_query)
    company = row.get("Company") or company_query
    playbook = _load_playbook(cfg)
    rt = ROUND_TEMPLATES.get(round_type)
    now = datetime.now(SGT)
    mode = "staff"
    jd = jd_text(cfg, company)                  # 本地 JD 档案（Job URL 可能空而档案在）
    jd_line = (row.get("Job URL")
               or (f"本地 JD 档案 ✓（{len(jd)} 字符）" if jd
                   else "⚠️ 无 JD 原文（P6：先要 JD）"))

    md: list[str] = [
        f"# {company} · 参谋 Brief" + (f" · {rt['label']}" if rt else ""),
        f"> 生成：{now.isoformat(timespec='minutes')} ｜ joblander W7 参谋 v1"
        "（LLM 战略层 + 确定性守卫层）",
        "",
        "## 战况",
        f"- 岗位：{row.get('Position') or '—'} ｜ 状态：{row.get('Status')} ｜ "
        f"优先级：{row.get('Priority') or '—'}",
        f"- 联系人：{row.get('Contact Person') or '—'}（{row.get('Contact Info') or '—'}）"
        f" ｜ Next：{row.get('Next Steps') or '—'}",
        f"- JD：{jd_line}",
    ]

    try:
        # effort=high：策略推演深度全在隐藏思考里，不占 1200 字产出预算
        out = json.loads(_strip_fences(llm.generate(
            _context_pack(cfg, row, company, round_type=round_type,
                          round_note=round_note, jd=jd),
            system=PREP_SYSTEM, json_mode=True, effort="high")))
        md += _staff_sections(out, rt)
    except Exception as e:                       # 参谋掉线：brief 必须照出（降级可见）
        mode = "fallback"
        md += ["", f"> ⚠️ 参谋 LLM 未接通（{str(e)[:100]}）——本份为确定性降级版"]
        md += _fallback_sections(cfg, row, rt, round_type, jd)

    if round_note:
        md += ["", "## 本场特别注意", round_note]

    # 只指路不复印（用户金标：口径/playbook/弹药他自己有，罗列=阅读负担）
    hot_ids = "、".join(p["id"] for p in playbook
                        if p.get("status") in ("needs_work", "improving"))
    md += ["", "---",
           "> 红线口径 → /system ｜ playbook 原文 → /playbook"
           + (f"（needs_work：{hot_ids}）" if hot_ids else "")
           + " ｜ 弹药全文 → 弹药库"]

    text = "\n".join(md) + "\n"
    out_dir = cfg.workspace_dir / "10-briefs"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = company.split("（")[0].strip().replace(" ", "-").replace("/", "-")
    out_path = out_dir / f"{now.strftime('%Y-%m-%d')}-{slug}-brief.md"
    out_path.write_text(text, encoding="utf-8")

    from joblander.company import timeline_upsert
    timeline_upsert(cfg, company, title_prefix="参谋 Brief", source="prep",
                    title=f"参谋 Brief：{rt['label'] if rt else '通用'}",
                    summary=("LLM 参谋" if mode == "staff" else "⚠️ 降级模板版")
                            + f" · {out_path.name}",
                    content_md="\n".join(md[2:]).lstrip())   # 时间线里不重复 H1 头

    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "brief.generated", "agent:prep",
        {"company": company, "path": str(out_path), "mode": mode,
         "round_type": round_type or "generic", "round_note": bool(round_note)})
    return out_path, text
