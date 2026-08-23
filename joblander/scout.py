"""Scout 侦察 — W1：原始信号 → 标准化机会提案（v0：贴入通道，无需 Gmail OAuth）。

输入：WhatsApp/InMail/邮件的粘贴文本或文件 → 抽取 + 三级查重（精确 → 集团互斥 → 相似提示）
输出：入池提案文件（人批后才建行，P6）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

SGT = timezone(timedelta(hours=8))

SCOUT_SYSTEM = """你是求职作战系统的侦察兵（Scout）。输入一段来信原文（WhatsApp、LinkedIn InMail、邮件均可）。

输出严格 JSON（中文，专名保留原文）：
{
  "category": "job_lead | followup | not_job",
  "company": "公司名；对方没说就写 null，不许猜",
  "position": "岗位名或 null",
  "location": "地点或 null",
  "comp_mentions": ["原文出现的一切薪酬数字/结构，逐字"],
  "contact": {"name": "...", "org": "猎头公司或 null", "channel": "whatsapp|linkedin|email|unknown"},
  "urls": [],
  "highlight": "一句短语（tracker Highlight 风格）",
  "suggested_next_step": "一句话动作",
  "confidence_notes": ["未知/存疑处标 ⚠️"]
}
category 判定（最重要的字段，想清楚再答）：
- job_lead：**新的工作机会**——猎头/招聘方主动接触、JD 分享、内推邀约
- followup：**已有申请/面试进程的跟进**——面试邀约与改期、流程进度通知、同一公司补发 JD、offer 相关往来
- not_job：**与求职无关**——产品营销、账单/交易通知、新闻简报、平台通知、社交动态。发件方是公司≠工作机会
纪律：对方没披露的字段一律 null；薪酬数字逐字保留；不编造。"""


def _followup_proposal(cfg, lead: dict[str, Any], row: dict[str, Any],
                       source_hint: str, raw_text: str, category: str,
                       jd_file: str = "") -> Path:
    """已有战线的跟进 → company.update 形态提案（与 Scribe 同構：field_diffs + body_entry，
    公司页时间线顶部审批）。转换是确定性代码，不二次调模型。"""
    from joblander.sentinel import Audience, Sentinel

    today = datetime.now(SGT).strftime("%Y-%m-%d")
    title = f"跟进（{source_hint}）：{lead.get('position') or '进展'}"
    lines = []
    if lead.get("highlight"):
        lines.append(f"- {lead['highlight']}")
    lines += [f"- 💰 {c}" for c in lead.get("comp_mentions") or []]
    lines += [f"- 🔗 {u}" for u in lead.get("urls") or []]
    if lead.get("suggested_next_step"):
        lines.append(f"- 建议动作：{lead['suggested_next_step']}")
    if jd_file:            # 公司已在战线：JD 附件直接落档（同公司页手动上传 JD）
        src = cfg.workspace_dir / jd_file
        if src.is_file():
            from joblander import company as companyfile
            saved = companyfile.save_upload(cfg, row.get("Company") or "",
                                            src.name.split("-", 1)[-1] or src.name,
                                            src.read_bytes(), kind="jd")
            src.unlink()
            lines.append(f"- 📎 JD 附件已入档：{saved.name}")
    excerpt = re.sub(r"\s+", " ", raw_text)[:400]
    body = f"### {today} {title}\n\n" + "\n".join(lines) + f"\n\n> 原文摘录：{excerpt}"

    field_diffs: dict[str, Any] = {}
    if lead.get("suggested_next_step"):          # 只建议 Next Steps；Status 变更留给人判断
        field_diffs["Next Steps"] = lead["suggested_next_step"]

    proposal = {
        "origin": "scout.followup",
        "category": category,
        "company": row.get("Company"),
        "notion_page_id": row.get("notion_page_id"),
        "field_diffs": field_diffs,
        "body_entry": body,
        "playbook_updates": [],
        "source_hint": source_hint,
        "raw_excerpt": excerpt,
        "sentinel": Sentinel.from_config(cfg).check(body, audience=Audience.INTERNAL).explain(),
        "approved": None,
    }
    import secrets
    out_dir = cfg.workspace_dir / "12-intake"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(SGT).strftime("%Y-%m-%d-%H%M%S")
    slug = (row.get("Company") or "x").split("（")[0].strip().replace(" ", "-").replace("/", "-")[:40]
    out = out_dir / f"{stamp}-{slug}-followup-{secrets.token_hex(2)}.json"
    out.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding="utf-8")

    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "scout.followup_proposed", "joblander.scout",
        {"company": row.get("Company"), "source": source_hint, "out": str(out)})
    return out


JUNK_TOKENS = {"pte", "ltd", "limited", "llc", "inc", "corp", "corporation", "co",
               "the", "asia", "pacific", "asiapac", "singapore", "sg", "hk",
               "international", "intl", "holdings", "private", "company"}


def _name_tokens(name: str) -> set[str]:
    """法人名归一化：去（备注）、去标点、去法域/后缀词——
    『GOOGLE ASIA PACIFIC PTE. LTD.』和 tracker 的『Google』要能对上。"""
    base = re.split(r"[（(]", name or "")[0]
    words = re.findall(r"[a-z0-9一-鿿]+", base.casefold())
    return {w for w in words if w not in JUNK_TOKENS}


def dedupe(rows: list[dict[str, Any]], company: str | None,
           groups: list[dict[str, Any]]) -> dict[str, Any]:
    """三级查重：精确/包含/法人名归一化 → 集团互斥 → 无冲突。"""
    if not company:
        return {"verdict": "unknown_company", "note": "公司未披露，人工确认后再查重"}
    q = company.casefold()
    qt = _name_tokens(company)
    for r in rows:
        name = (r.get("Company") or "").casefold()
        nt = _name_tokens(r.get("Company") or "")
        if q == name or q in name or name in q \
                or (qt and nt and (qt <= nt or nt <= qt)):
            return {"verdict": "duplicate", "existing": r.get("Company"),
                    "url": r.get("url") or r.get("notion_page_id")}
    terminal = {"Terminated", "Not Apply", "Rejected", "Withdrawn"}
    for g in groups:
        members = [m.casefold() for m in g.get("members", [])]
        if any(q in m or m in q for m in members):
            active = [r.get("Company") for r in rows
                      if (r.get("Status") not in terminal)
                      and any(mm in (r.get("Company") or "").casefold()
                              for mm in members)]
            if active:
                return {"verdict": "group_conflict", "group": g.get("group"),
                        "active_members": active, "note": g.get("rule", "")}
    return {"verdict": "new"}


def resolve_intake_text(cfg, text: str, source_hint: str = "paste") -> tuple[str, str]:
    """贴入的是纯链接 → 抓页面正文当原文再走抽取（与公司页 JD 链接层同思路）。
    MCF 走结构化 API（含薪资/YoE/skills，初筛直接有料）；其余通用抓取。
    抓不到就 ValueError 明说——让他贴原文，不硬塞空壳进管线。"""
    t = text.strip()
    if not re.fullmatch(r"https?://\S+", t):
        return text, source_hint
    m = re.search(r"mycareersfuture\.gov\.sg/\S*?([0-9a-f]{32})", t)
    if m:
        from joblander.sourcing import _strip_html, mcf_job_detail
        try:
            d = mcf_job_detail(m.group(1))
        except Exception as e:
            raise ValueError(f"MCF 详情拉取失败（{e}）——把 JD 原文贴进来吧")
        sal = d.get("salary") or {}
        parts = [f"岗位：{d.get('title') or ''}",
                 f"公司：{((d.get('postedCompany') or {}).get('name')) or ''}"]
        if sal.get("minimum") or sal.get("maximum"):
            parts.append(f"薪资：{sal.get('minimum')}-{sal.get('maximum')} "
                         f"{(sal.get('type') or {}).get('salaryType') or ''}")
        if d.get("minimumYearsExperience") is not None:
            parts.append(f"最低年限：{d['minimumYearsExperience']} 年")
        skills = "、".join(s.get("skill", "") for s in (d.get("skills") or [])[:15])
        if skills:
            parts.append(f"技能：{skills}")
        parts += ["", _strip_html(d.get("description") or "")[:8000],
                  f"\n原始链接：{t}"]
        return "\n".join(parts), "mcf"
    from joblander.researcher import fetch_url
    try:
        body = fetch_url(t, timeout=20)
    except Exception as e:
        raise ValueError(f"链接抓取失败（{e}）——把 JD 原文贴进来吧")
    if not body or len(body.strip()) < 200:
        raise ValueError("链接抓不到正文（LinkedIn 常要登录）——把 JD 原文贴进来吧")
    return (f"{body[:12000]}\n\n原始链接：{t}",
            "linkedin" if "linkedin.com" in t else "link")


def intake(cfg, llm, raw_text: str, source_hint: str = "paste",
           jd_file: str = "") -> Path | None:
    """贴入 → 抽取 → 查重 → 提案文件（12-intake/），不建任何行。
    jd_file：随录入上传的 JD 附件（workspace 相对路径，暂存 12-intake/files/）——
    新公司随提案走，批准时落公司 jd/；已有战线直接落该公司 jd/。"""
    from joblander.prep import _load_projection
    from joblander.scribe import _strip_fences

    raw = llm.generate(f"来源渠道提示：{source_hint}\n\n原文：\n{raw_text[:20000]}",
                       system=SCOUT_SYSTEM, json_mode=True)
    lead = json.loads(_strip_fences(raw))

    # 分类闸（2026-08-07 实战教训 ×2：①一次 gmail 扫描进 8 条无公司名提案；
    # ②理财平台交易通知——LLM 判了非机会但旧代码没读判定字段就入队）
    category = lead.get("category") or (
        "not_job" if lead.get("is_opportunity") is False else "job_lead")
    no_signal = not (lead.get("company") or "").strip() \
        and not (lead.get("position") or "").strip()
    if category == "not_job" or no_signal:
        from joblander.eventlog import EventLog
        EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
            "lead.discarded", "joblander.scout",
            {"reason": "not_job" if category == "not_job" else "no_company_no_position",
             "company": lead.get("company"),
             "excerpt": re.sub(r"\s+", " ", raw_text)[:160]})
        return None

    try:                                          # 排除词对所有渠道生效（不只 MCF）
        from joblander.sourcing import load_prefs
        excl = [e.casefold() for e in (load_prefs(cfg).get("exclude") or [])]
    except Exception:
        excl = []
    title = (lead.get("position") or "").casefold()
    if excl and title and any(e in title for e in excl):
        from joblander.eventlog import EventLog
        EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
            "lead.discarded", "joblander.scout",
            {"reason": "exclude_keyword", "company": lead.get("company"),
             "position": lead.get("position")})
        return None

    rows = _load_projection(cfg)
    groups = cfg.policy.get("group_exclusivity", []) or cfg.raw.get("policy", {}).get("group_exclusivity", [])
    verdict = dedupe(rows, lead.get("company"), groups)

    if verdict.get("verdict") == "duplicate":
        # 已在打的公司来跟进（面试邀约/JD 补充/进度）→ 不是新机会，是该公司的更新提案：
        # 字段建议 + 时间线条目，落在公司页带上下文批（UI v2.1 属地原则）
        row = next((r for r in rows if r.get("Company") == verdict.get("existing")), None)
        if row is not None:
            return _followup_proposal(cfg, lead, row, source_hint, raw_text, category,
                                      jd_file=jd_file)

    try:                                          # fit 评分 + requirements 初筛：失败不阻塞入队
        from joblander.sourcing import assess_fit
        fit = assess_fit(cfg, llm, lead, jd_text=raw_text)   # 来信原文常含 JD 要求
    except Exception:
        fit = {}
    if not lead.get("comp_mentions") and lead.get("position"):
        try:                                      # 对方没报薪资 → 补市场 band（决策要有数）
            from joblander.sourcing import market_band
            ref = market_band(lead["position"])
            if ref:
                lead["market_ref"] = ref
        except Exception:
            pass

    proposal = {
        "kind": "lead.intake",
        "lead": lead,
        "dedupe": verdict,
        "source_hint": source_hint,
        "fit": fit,
        "raw_excerpt": re.sub(r"\s+", " ", raw_text)[:500],
        "jd_file": jd_file,
        "approved": None,
    }
    out_dir = cfg.workspace_dir / "12-intake"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(SGT).strftime("%Y-%m-%d-%H%M%S")
    slug = (lead.get("company") or "unknown").replace(" ", "-").replace("/", "-")[:40]
    out = out_dir / f"{stamp}-{slug}.json"
    out.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding="utf-8")

    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "scout.lead_proposed", "joblander.scout",
        {"company": lead.get("company"), "dedupe": verdict.get("verdict"), "out": str(out)})
    return out
