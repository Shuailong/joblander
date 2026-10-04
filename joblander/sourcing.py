"""Sourcing 主动侦察（W1 扩展）— 多源找新机会 + 偏好驱动的 fit 评估。

渠道分级（诚实边界，DESIGN §15 v2.2）：
- Gmail（含 LinkedIn Job Alert 邮件）/ MyCareersFuture 公开 API → 全自动（夜间 + 手动）
- LinkedIn Inbox/Search、WhatsApp → 无 API 不爬（红线）：偏好拼深链一键打开 + 人工贴入

偏好（求职意向/关键词/排除词/地点）存私有 workspace（02-targets/sourcing-prefs.yaml），
引擎零硬编码；fit 评估只消费偏好文本，不接触任何薪酬红线数字。
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from joblander.tz import LOCAL_TZ as SGT   # 单一来源，JOBLANDER_TZ 可覆盖
PREFS_REL = "02-targets/sourcing-prefs.yaml"
MCF_API = "https://api.mycareersfuture.gov.sg/v2/search"
MCF_JOB_URL = "https://www.mycareersfuture.gov.sg/job/{uuid}"


# ---------- 偏好 ----------

def load_prefs(cfg) -> dict[str, Any]:
    p = cfg.workspace_dir / PREFS_REL
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def save_prefs(cfg, patch: dict[str, Any]) -> dict[str, Any]:
    prefs = load_prefs(cfg)
    prefs.update(patch)
    prefs["updated"] = datetime.now(SGT).isoformat(timespec="seconds")
    p = cfg.workspace_dir / PREFS_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(prefs, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")
    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "sourcing.prefs_updated", "human_direct", {"fields": sorted(patch.keys())})
    return prefs


def prefs_text(prefs: dict[str, Any]) -> str:
    """偏好 → fit 评估用的紧凑文本。"""
    lines = []
    if prefs.get("intent"):
        lines.append(f"求职意向：{prefs['intent']}")
    if prefs.get("keywords"):
        lines.append(f"目标岗位关键词：{'、'.join(prefs['keywords'])}")
    if prefs.get("locations"):
        lines.append(f"地点偏好：{'、'.join(prefs['locations'])}")
    if prefs.get("exclude"):
        lines.append(f"排除：{'、'.join(prefs['exclude'])}")
    if prefs.get("notes"):
        lines.append(f"补充：{prefs['notes']}")
    return "\n".join(lines) or "（未配置偏好）"


def search_links(prefs: dict[str, Any]) -> list[dict[str, str]]:
    """无 API 渠道的深链（人工半自动）：按偏好拼好，一键打开自己搜。"""
    out = []
    loc = (prefs.get("locations") or ["Singapore"])[0]
    for kw in (prefs.get("keywords") or [])[:5]:
        q = urllib.parse.quote(kw)
        out.append({"label": f"LinkedIn 24h · {kw}",
                    "url": f"https://www.linkedin.com/jobs/search/?keywords={q}"
                           f"&location={urllib.parse.quote(loc)}&f_TPR=r86400"})
        out.append({"label": f"MCF · {kw}",
                    "url": f"https://www.mycareersfuture.gov.sg/search?search={q}"
                           f"&sortBy=new_posting_date"})
    return out


# ---------- fit 评估（偏好 × 岗位 → 1-5） ----------

FIT_SYSTEM = """你是求职作战系统的侦察评估官。对照候选人的【偏好】与【履历摘要】，给一个新岗位打匹配分并做 requirements 初筛。
输出严格 JSON：
{"fit": 1-5, "why": "一句话：为什么值得看/不值得看",
 "flags": ["注意点，如：中介代招、外包/合同岗、方向偏差"],
 "req_gaps": [{"req": "逐字摘出的 JD 硬性要求（YoE/语言/签证/学历/必备技能/行业经验）",
               "verdict": "不符|存疑", "note": "对照履历的一句话，如『简历约 6 年，JD 要 8 年』"}]}
初筛纪律：只抠**硬性** requirements（must-have），nice-to-have 不算；履历里明确满足的不列；
无法从履历判断的标『存疑』不许猜。**任何一条『不符』→ fit ≤ 2**（如 JD 要求泰语/特定行业年限）。
口径：5=高度对口马上看；4=对口；3=可看可不看；2=勉强/有硬伤；1=明显不符。
纪律：**挑剔是你的职责——分数的价值在区分度，全给 4 分等于没评**。偏好中若给出薪酬过滤线，
挂牌 band 明显低于线 → fit ≤ 2 并在 why 里点明；偏好未提的维度不猜。中介代招必进 flags。
没给 JD 正文时 req_gaps 给空数组，只按偏好打分。"""


def _profile_digest(cfg, limit: int = 12000) -> str:
    """候选人履历摘要（初筛/画像的对照面）：主源 = 弹药库（唯一事实来源——
    任期起止、战绩、技术栈、学术资产都在）。profile.files 仅作补充配置，
    避免再喂 resume.html 这类弹药库的下游产物（重复 + HTML 噪音）。"""
    from joblander.company import _file_text
    parts = []
    bank = cfg.workspace_dir / "03-materials" / "achievement-bank.md"
    if bank.exists():
        parts.append(bank.read_text(encoding="utf-8"))
    for rel in (cfg.raw.get("profile", {}).get("files") or []):
        p = cfg.workspace_dir / rel
        if p.exists() and p.name != "achievement-bank.md":
            parts.append(_file_text(p))
    return "\n\n".join(parts)[:limit]


def assess_fit(cfg, llm, lead: dict[str, Any], jd_text: str = "") -> dict[str, Any]:
    prefs = load_prefs(cfg)
    if not prefs:
        return {}
    brief = {k: lead.get(k) for k in ("company", "position", "location",
                                      "comp_mentions", "highlight", "skills", "min_yoe")}
    profile = _profile_digest(cfg)
    from joblander.scribe import _strip_fences
    raw = llm.generate(
        f"候选人偏好：\n{prefs_text(prefs)}\n\n"
        f"候选人履历摘要：\n{profile or '（弹药库为空——req_gaps 全部标存疑）'}\n\n"
        f"岗位线索：\n{json.dumps(brief, ensure_ascii=False)}\n\n"
        f"JD 正文：\n{(jd_text or '（无）')[:6000]}",
        system=FIT_SYSTEM, json_mode=True)
    try:
        fit = json.loads(_strip_fences(raw))
        return {"fit": int(fit.get("fit", 0)) or None,
                "why": fit.get("why", ""), "flags": fit.get("flags") or [],
                "req_gaps": fit.get("req_gaps") or []}
    except Exception:
        return {}


# ---------- MyCareersFuture 自动抓取 ----------

def mcf_search(keyword: str, limit: int = 20, page: int = 0,
               timeout: int = 20) -> list[dict[str, Any]]:
    body = json.dumps({"sessionId": "", "search": keyword,
                       "postingCompany": []}).encode()
    req = urllib.request.Request(
        f"{MCF_API}?limit={limit}&page={page}", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (joblander)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    return data.get("results", [])


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def mcf_job_detail(uuid: str, timeout: int = 20) -> dict[str, Any]:
    """岗位详情：JD 正文 + 结构化 skills + minimumYearsExperience（初筛的原料）。"""
    req = urllib.request.Request(
        f"https://api.mycareersfuture.gov.sg/v2/jobs/{uuid}",
        headers={"User-Agent": "Mozilla/5.0 (joblander)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def mcf_to_lead(job: dict[str, Any], detail: dict[str, Any] | None = None) -> dict[str, Any]:
    sal = job.get("salary") or {}
    comp = []
    if sal.get("minimum") and sal.get("maximum"):
        cycle = ((sal.get("type") or {}).get("salaryType") or "Monthly")
        comp.append(f"{sal['minimum']}–{sal['maximum']} SGD/{cycle}（MCF 挂牌）")
    md = job.get("metadata") or {}
    url = md.get("jobDetailsUrl") or MCF_JOB_URL.format(uuid=job.get("uuid", ""))
    lead = {
        "category": "job_lead",
        "company": (job.get("postedCompany") or {}).get("name"),
        "position": job.get("title"),
        "location": "Singapore",
        "comp_mentions": comp,
        "urls": [url],
        "highlight": f"MCF 挂牌 {md.get('newPostingDate') or ''}"
                     + (f"；{comp[0]}" if comp else ""),
        "suggested_next_step": "看 JD 原文，对口就投",
        "contact": {"channel": "mcf"},
    }
    if detail:
        lead["jd_excerpt"] = _strip_html(detail.get("description") or "")[:2500]
        lead["skills"] = [s.get("skill") for s in (detail.get("skills") or [])][:15]
        if detail.get("minimumYearsExperience") is not None:
            lead["min_yoe"] = detail["minimumYearsExperience"]
    return lead


def market_band(title: str, limit: int = 20) -> str:
    """同类岗市场参考（MCF 实时挂牌分布）——线索无薪资时入库补上，代替静态调研文档。"""
    try:
        jobs = mcf_search(title, limit=limit)
    except Exception:
        return ""
    los: list[float] = []
    his: list[float] = []
    for j in jobs:
        s = j.get("salary") or {}
        if ((s.get("type") or {}).get("salaryType") or "Monthly") != "Monthly":
            continue
        if s.get("minimum") and s.get("maximum"):
            los.append(s["minimum"])
            his.append(s["maximum"])
    if len(los) < 5:                              # 样本太少不给数（宁缺毋错）
        return ""
    los.sort()
    his.sort()
    lo, hi = los[len(los) // 4], his[(len(his) * 3) // 4]
    return f"市场参考 {lo:,.0f}–{hi:,.0f} SGD/月（MCF 同类岗 {len(los)} 条挂牌，p25–p75）"


def _seen_path(cfg, source: str = "mcf") -> Path:
    return cfg.workspace_dir / "19-sourcing" / f"{source}-seen.json"


class _Run:
    """一轮主动侦察的共用骨架：去重账本（跨轮）、同轮 (公司,岗位) 去重、排除词、
    已在库查重、fit 评分、写入池提案。各渠道只负责「搜 → 转 lead → 拉 JD 详情」。"""

    def __init__(self, cfg, llm, source: str, days: int):
        from joblander.eventlog import EventLog
        from joblander.prep import _load_projection
        self.cfg, self.llm, self.source = cfg, llm, source
        self.prefs = load_prefs(cfg)
        self.log = EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl")
        self.sp = _seen_path(cfg, source)
        self.seen: dict[str, str] = (json.loads(self.sp.read_text(encoding="utf-8"))
                                     if self.sp.exists() else {})
        try:
            self.rows = _load_projection(cfg)
        except FileNotFoundError:
            self.rows = []
        self.groups = cfg.policy.get("group_exclusivity", [])
        self.cutoff = (datetime.now(SGT) - timedelta(days=days)).strftime("%Y-%m-%d")
        self.run_keys: set[tuple[str, str]] = set()
        self.excl = [e.casefold() for e in self.prefs.get("exclude") or []]
        self.outs: list[Path] = []
        self.fetched = 0

    def admit(self, uid: str, posted: str, company: str, title: str) -> bool:
        """不需要 JD 详情就能判的闸：见过 / 过期 / 同轮重复 / 排除词。过闸才值得拉详情。"""
        if not uid or uid in self.seen or (posted and posted < self.cutoff):
            return False
        rk = ((company or "").casefold(), (title or "").casefold())
        if rk in self.run_keys:
            self.seen[uid] = posted or "dup"
            return False
        self.run_keys.add(rk)
        self.seen[uid] = posted or datetime.now(SGT).strftime("%Y-%m-%d")
        if any(e in (title or "").casefold() for e in self.excl):
            self.log.append("lead.discarded", f"joblander.sourcing.{self.source}",
                            {"reason": "exclude_keyword", "position": title})
            return False
        return True

    def tracked(self, lead: dict[str, Any]) -> dict[str, Any] | None:
        """已在库的公司：你已经在打这场仗，主动抓到的挂牌岗不构成新信息 → 丢弃记账。
        （对方来信的跟进走 scout.intake，那才转公司页更新提案——语义不同）"""
        from joblander.scout import dedupe
        verdict = dedupe(self.rows, lead.get("company"), self.groups)
        if verdict.get("verdict") == "duplicate":
            self.log.append("lead.discarded", f"joblander.sourcing.{self.source}",
                            {"reason": "already_tracked", "existing": verdict.get("existing"),
                             "company": lead.get("company"), "position": lead.get("position")})
            return None
        return verdict

    def propose(self, lead: dict[str, Any], verdict: dict[str, Any], kw: str, uid: str) -> None:
        proposal = {
            "kind": "lead.intake", "lead": lead, "dedupe": verdict,
            "source_hint": self.source,
            "fit": assess_fit(self.cfg, self.llm, lead, jd_text=lead.get("jd_excerpt", "")),
            "raw_excerpt": f"{self.source.upper()} {kw} · {lead.get('position')} @ {lead.get('company')}",
            "approved": None,
        }
        out_dir = self.cfg.workspace_dir / "12-intake"
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = (lead.get("company") or "x").replace(" ", "-").replace("/", "-")[:40]
        out = out_dir / f"{datetime.now(SGT).strftime('%Y-%m-%d-%H%M%S')}-{slug}-{uid[-6:]}.json"
        out.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding="utf-8")
        self.log.append("scout.lead_proposed", f"joblander.sourcing.{self.source}",
                        {"company": lead.get("company"), "fit": (proposal["fit"] or {}).get("fit"),
                         "source": self.source, "out": str(out)})
        self.outs.append(out)

    def finish(self, keywords: list[str]) -> list[Path]:
        self.sp.parent.mkdir(parents=True, exist_ok=True)
        self.sp.write_text(json.dumps(self.seen, ensure_ascii=False, indent=0), encoding="utf-8")
        self.log.append(f"sourcing.{self.source}_run", "joblander.sourcing",
                        {"keywords": keywords, "fetched": self.fetched, "proposed": len(self.outs)})
        return self.outs


def source_mcf(cfg, llm, days: int = 2, limit_per_kw: int = 20) -> list[Path]:
    """按偏好关键词抓 MCF 新岗 → 查重 → fit 评估 → 入池提案。幂等（uuid 去重）。"""
    run = _Run(cfg, llm, "mcf", days)
    keywords = run.prefs.get("keywords") or []
    if not keywords:
        run.log.append("sourcing.mcf_skipped", "joblander.sourcing", {"reason": "no_keywords"})
        return []
    for kw in keywords:
        try:
            jobs = mcf_search(kw, limit=limit_per_kw)
        except Exception as e:
            run.log.append("sourcing.mcf_error", "joblander.sourcing", {"kw": kw, "error": str(e)})
            continue
        run.fetched += len(jobs)
        for job in jobs:
            uuid = job.get("uuid") or ""
            posted = (job.get("metadata") or {}).get("newPostingDate") or ""
            lead = mcf_to_lead(job)
            if not run.admit(uuid, posted, lead.get("company") or "", lead.get("position") or ""):
                continue
            verdict = run.tracked(lead)
            if verdict is None:
                continue
            try:                                 # JD 正文供 requirements 初筛；拉不到不阻塞
                lead = mcf_to_lead(job, mcf_job_detail(uuid))
            except Exception:
                pass
            run.propose(lead, verdict, kw, uuid)
    return run.finish(keywords)


# ---------- LinkedIn 公开职位（免登录 guest 接口） ----------
# 条款灰区：只读公开列表、不登录、每人每晚几次请求、可在设置里关（features.linkedin）。
# 接口随时可能改版或限流——解析失败、被拦都只记账不抛，不拖垮夜扫。

LI_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LI_DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
LI_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")


def _li_get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": LI_UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _txt(s: str) -> str:
    import html as _h
    return _h.unescape(_strip_html(s))


def parse_linkedin_cards(page: str) -> list[dict[str, str]]:
    out = []
    for card in page.split("<li")[1:]:
        m = re.search(r"urn:li:jobPosting:(\d+)", card)
        if not m:
            continue
        g = lambda pat: (lambda x: _txt(x.group(1)) if x else "")(re.search(pat, card, re.S))
        href = re.search(r'base-card__full-link[^>]*href="([^"?]+)', card)
        posted = re.search(r'<time[^>]*datetime="([\d-]+)"', card)
        out.append({"id": m.group(1),
                    "title": g(r'base-search-card__title">(.*?)</h3>'),
                    "company": g(r'base-search-card__subtitle">(.*?)</h4>'),
                    "location": g(r'job-search-card__location">(.*?)</span>'),
                    "posted": posted.group(1) if posted else "",
                    "url": href.group(1) if href else f"https://www.linkedin.com/jobs/view/{m.group(1)}"})
    return out


def linkedin_search(keyword: str, location: str, hours: int = 48, start: int = 0) -> list[dict[str, str]]:
    q = urllib.parse.urlencode({"keywords": keyword, "location": location,
                                "f_TPR": f"r{hours * 3600}", "start": start})
    return parse_linkedin_cards(_li_get(f"{LI_SEARCH}?{q}"))


def parse_linkedin_detail(page: str) -> dict[str, Any]:
    m = re.search(r"show-more-less-html__markup[^>]*>(.*?)</div>", page, re.S)
    crit = {k.strip(): _txt(v) for k, v in re.findall(
        r'description__job-criteria-subheader">\s*(.*?)\s*</h3>\s*<span[^>]*>(.*?)</span>', page, re.S)}
    return {"description": _txt(m.group(1)) if m else "", "criteria": crit}


def linkedin_to_lead(card: dict[str, str], detail: dict[str, Any] | None = None) -> dict[str, Any]:
    lead = {
        "category": "job_lead",
        "company": card.get("company"),
        "position": card.get("title"),
        "location": card.get("location") or "",
        "comp_mentions": [],
        "urls": [card.get("url")],
        "highlight": f"LinkedIn 挂牌 {card.get('posted') or ''}".strip(),
        "suggested_next_step": "看 JD 原文，对口就投",
        "contact": {"channel": "linkedin"},
    }
    if detail:
        lead["jd_excerpt"] = (detail.get("description") or "")[:2500]
        crit = detail.get("criteria") or {}
        if crit.get("Seniority level"):
            lead["highlight"] += f"；{crit['Seniority level']}"
    return lead


def source_linkedin(cfg, llm, days: int = 2, pages_per_kw: int = 1) -> list[Path]:
    """按偏好关键词 × 首选地点抓 LinkedIn 公开职位 → 与 MCF 同一条查重/评分/入池管线。"""
    import time
    from joblander.wizard import features
    run = _Run(cfg, llm, "linkedin", days)
    keywords = run.prefs.get("keywords") or []
    if not features(cfg)["linkedin"] or not keywords:
        return []
    loc = (run.prefs.get("locations") or ["Singapore"])[0]
    for kw in keywords:
        for page in range(pages_per_kw):
            try:
                cards = linkedin_search(kw, loc, hours=days * 24, start=page * 10)
            except Exception as e:
                run.log.append("sourcing.linkedin_error", "joblander.sourcing", {"kw": kw, "error": str(e)[:200]})
                break
            run.fetched += len(cards)
            for card in cards:
                if not run.admit(card["id"], card["posted"], card["company"], card["title"]):
                    continue
                lead = linkedin_to_lead(card)
                verdict = run.tracked(lead)
                if verdict is None:
                    continue
                try:
                    time.sleep(1)                  # 礼貌间隔：一人一晚几十个请求，不扎堆
                    lead = linkedin_to_lead(card, parse_linkedin_detail(
                        _li_get(LI_DETAIL.format(id=card["id"]))))
                except Exception:
                    pass
                run.propose(lead, verdict, kw, card["id"])
            if len(cards) < 10:
                break
    return run.finish(keywords)


def source_all(cfg, llm, days: int = 2) -> dict[str, int]:
    """夜扫与「立即搜」的统一入口：各渠道互不拖累。"""
    out = {}
    for name, fn in (("mcf", source_mcf), ("linkedin", source_linkedin)):
        try:
            out[name] = len(fn(cfg, llm, days=days))
        except Exception as e:                       # noqa: BLE001
            out[name] = 0
            from joblander.eventlog import EventLog
            EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
                "sourcing.error", "joblander.sourcing", {"source": name, "error": str(e)[:200]})
    return out
