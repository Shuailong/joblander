"""目标公司定向搜索 — 先定公司，再找这家里适合我的岗位（与关键词搜索互补）。

偏好里列出想去的公司（名字或招聘页链接）。每家：
1. 认出它用的招聘系统：Greenhouse / Lever / Ashby 有免登录的公开 JSON，一次拿全部在招岗位；
   贴链接直接认，只给名字就按常见写法试 slug（结果缓存，一周重试一次）。
2. 认不出（Workday 等）→ 退回用公司名搜 LinkedIn 公开职位 + MCF，再按公司名过滤——覆盖不全，界面明说。
3. 地点用代码先筛（零成本）→ 只把标题清单丢给 LLM 挑几条（一家一次便宜调用）→
   挑中的才走常规 fit 评分 + 入池提案。大厂动辄几百上千岗，逐条评分会烧光额度。

跨轮去重账本 19-sourcing/targets-seen.json：看过的岗不再挑第二遍，夜扫只处理新挂出来的。
每家的覆盖情况写 19-sourcing/targets-status.json 给页面展示。
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from joblander.sourcing import (SGT, _Run, _profile_digest, _strip_html, _txt,
                                load_prefs, prefs_text)

UA = {"User-Agent": "Mozilla/5.0 (joblander)"}
ATS = {
    "greenhouse": {"api": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
                   "board": "https://job-boards.greenhouse.io/{slug}"},
    "lever": {"api": "https://api.lever.co/v0/postings/{slug}?mode=json",
              "board": "https://jobs.lever.co/{slug}"},
    "ashby": {"api": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
              "board": "https://jobs.ashbyhq.com/{slug}"},
}
URL_PATTERNS = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)"),
    ("greenhouse", r"boards-api\.greenhouse\.io/v1/boards/([\w-]+)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([\w-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([\w.-]+)"),
]
SUFFIXES = {"inc", "ltd", "llc", "pte", "co", "corp", "corporation", "limited", "plc", "gmbh"}
MAX_TITLES = 400        # 一次丢给挑选器的标题上限；多出来的留到下一轮
MAX_PICKS = 5           # 每家每轮最多细评几条（每条一次评分调用）
RETRY_DAYS = 7          # 认不出招聘系统的公司，隔几天再试


def _get_json(url: str, timeout: int = 25) -> Any:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


# ---------- 认招聘系统 ----------

def parse_board_url(entry: str) -> tuple[str, str] | None:
    for ats, pat in URL_PATTERNS:
        m = re.search(pat, entry, re.I)
        if m:
            return ats, m.group(1).lower()
    return None


def slug_candidates(name: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", name.casefold()) if w not in SUFFIXES]
    out = []
    for s in ("".join(words), "-".join(words)):
        if s and s not in out:
            out.append(s)
    return out


def fetch_board(ats: str, slug: str) -> list[dict[str, Any]]:
    """拉一家的全部在招岗位 → 统一格式。404 抛 HTTPError，交给调用方判断。"""
    data = _get_json(ATS[ats]["api"].format(slug=urllib.parse.quote(slug)))
    jobs = []
    if ats == "greenhouse":
        for j in data.get("jobs") or []:
            jobs.append({"uid": f"gh:{slug}:{j.get('id')}", "title": j.get("title") or "",
                         "location": (j.get("location") or {}).get("name") or "",
                         "url": j.get("absolute_url") or "",
                         "posted": (j.get("first_published") or j.get("updated_at") or "")[:10],
                         "company": j.get("company_name") or "",
                         "jd": _txt(html.unescape(j.get("content") or ""))})
    elif ats == "lever":
        for j in data if isinstance(data, list) else []:
            cat = j.get("categories") or {}
            locs = [cat.get("location") or ""] + list(cat.get("allLocations") or [])
            ts = j.get("createdAt")
            jobs.append({"uid": f"lv:{slug}:{j.get('id')}", "title": j.get("text") or "",
                         "location": " / ".join(dict.fromkeys(l for l in locs if l)),
                         "url": j.get("hostedUrl") or "",
                         "posted": (datetime.fromtimestamp(ts / 1000, SGT).strftime("%Y-%m-%d")
                                    if isinstance(ts, (int, float)) else ""),
                         "company": "",
                         "jd": " ".join(filter(None, [j.get("descriptionPlain"),
                                                      *(_strip_html(x.get("content") or "")
                                                        for x in j.get("lists") or []),
                                                      j.get("additionalPlain")]))})
    elif ats == "ashby":
        for j in data.get("jobs") or []:
            if j.get("isListed") is False:
                continue
            locs = [j.get("location") or ""] + [s.get("location") or ""
                                                for s in j.get("secondaryLocations") or []]
            if j.get("isRemote"):
                locs.append("Remote")
            jobs.append({"uid": f"as:{slug}:{j.get('id')}", "title": j.get("title") or "",
                         "location": " / ".join(dict.fromkeys(l for l in locs if l)),
                         "url": j.get("jobUrl") or "",
                         "posted": (j.get("publishedAt") or "")[:10],
                         "company": "",
                         "jd": j.get("descriptionPlain") or ""})
    return jobs


def _boards_path(cfg) -> Path:
    return cfg.workspace_dir / "19-sourcing" / "target-boards.json"


def _load_json(p: Path) -> dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def _save_json(p: Path, data: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


GENERIC = {"holdings", "technologies", "technology", "labs", "group", "global",
           "international", "software", "systems", "company"}


def _name_ok(entry: str, company: str) -> bool:
    """Greenhouse 回带公司名：猜中的 slug 若是同名不同家（Kite ≠ Kite Realty），不认。
    看板公司名里的实词都得在他写的名字里出现；Holdings / Labs 这类泛词不算。"""
    from joblander.scout import _name_tokens
    a, b = _name_tokens(entry), _name_tokens(company) - GENERIC
    return not b or b <= a


def resolve(cfg, entry: str, cache: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    """→ (board 信息, 已拉到的岗位或 None)。board = {ats, slug, name}；ats 为空 = 认不出。"""
    hit = parse_board_url(entry)
    if hit:
        ats, slug = hit
        jobs = fetch_board(ats, slug)
        name = next((j["company"] for j in jobs if j["company"]), "") or slug.replace("-", " ").title()
        return {"ats": ats, "slug": slug, "name": name}, jobs
    key = entry.casefold()
    c = cache.get(key)
    if c and c.get("ats"):
        try:
            return c, fetch_board(c["ats"], c["slug"])
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            cache.pop(key, None)                 # 换了招聘系统 → 重新认
    elif c and c.get("checked", "") > (datetime.now(SGT) - timedelta(days=RETRY_DAYS)).strftime("%Y-%m-%d"):
        return c, None
    for slug in slug_candidates(entry):
        for ats in ATS:
            try:
                jobs = fetch_board(ats, slug)
            except urllib.error.HTTPError:
                continue
            if jobs and _name_ok(entry, jobs[0]["company"]):
                board = {"ats": ats, "slug": slug, "name": entry}
                cache[key] = board
                return board, jobs
    board = {"ats": "", "name": entry, "checked": datetime.now(SGT).strftime("%Y-%m-%d")}
    cache[key] = board
    return board, None


# ---------- 退路：按公司名搜公开渠道 ----------

def search_fallback(cfg, name: str, loc: str) -> list[dict[str, Any]]:
    """认不出招聘系统的公司：LinkedIn（开着的话）+ MCF 用公司名搜，只留公司名对得上的。"""
    from joblander import sourcing
    from joblander.scout import _name_tokens
    from joblander.wizard import features
    want = _name_tokens(name)
    match = lambda c: bool(want) and want <= _name_tokens(c or "")
    jobs: list[dict[str, Any]] = []
    if features(cfg)["linkedin"]:
        for start in (0, 10):
            try:
                cards = sourcing.linkedin_search(name, loc, hours=30 * 24, start=start)
            except Exception:
                break
            jobs += [{"uid": f"li:{c['id']}", "title": c["title"], "location": c["location"],
                      "url": c["url"], "posted": c["posted"], "company": c["company"],
                      "jd": "", "li_id": c["id"]} for c in cards if match(c["company"])]
            if len(cards) < 10:
                break
    try:
        for j in sourcing.mcf_search(name, limit=50):
            co = (j.get("postedCompany") or {}).get("name") or ""
            if match(co):
                md = j.get("metadata") or {}
                jobs.append({"uid": f"mcf:{j.get('uuid')}", "title": j.get("title") or "",
                             "location": "Singapore", "company": co,
                             "url": md.get("jobDetailsUrl") or sourcing.MCF_JOB_URL.format(uuid=j.get("uuid")),
                             "posted": md.get("newPostingDate") or "", "jd": "",
                             "mcf": j})
    except Exception:
        pass
    return jobs


# ---------- 挑选 ----------

SCREEN_SYSTEM = """你是求职侦察的初筛员。候选人点名想去下面这家公司，给你的是它在招岗位的标题清单（编号|标题|地点）。
对照候选人的【偏好】与【履历摘要】，挑出值得细看 JD 的岗位：方向对口、级别大致相当（明显过高或过低的不挑）。
宁缺毋滥，最多挑 {n} 个，按匹配度从高到低排。一个都不合适就给空数组。
输出严格 JSON：{{"picks": [编号, ...]}}"""


def in_locations(job: dict[str, Any], locations: list[str]) -> bool:
    loc = (job.get("location") or "").casefold()
    return not locations or not loc or any(l.casefold() in loc for l in locations)


def screen_titles(cfg, llm, company: str, jobs: list[dict[str, Any]],
                  n: int = MAX_PICKS) -> list[dict[str, Any]]:
    if not jobs:
        return []
    from joblander.scribe import _strip_fences
    listing = "\n".join(f"{i}|{j['title']}|{j.get('location') or '-'}" for i, j in enumerate(jobs))
    raw = llm.generate(
        f"公司：{company}\n\n候选人偏好：\n{prefs_text(load_prefs(cfg))}\n\n"
        f"候选人履历摘要：\n{_profile_digest(cfg, limit=3000) or '（空）'}\n\n"
        f"在招岗位：\n{listing}",
        system=SCREEN_SYSTEM.format(n=n), json_mode=True)
    picks = json.loads(_strip_fences(raw)).get("picks") or []
    out, used = [], set()
    for i in picks:
        if isinstance(i, int) and 0 <= i < len(jobs) and i not in used:
            used.add(i)
            out.append(jobs[i])
    return out[:n]


_TEXT = {"zh": {"board": "官网招聘页", "fallback": "按公司名搜到", "next": "看 JD 原文；想投就批准入池，再按这个岗位定制简历"},
         "en": {"board": "Careers page", "fallback": "Found by company name",
                "next": "Read the JD; approve it, then tailor your resume to this role"}}


def to_lead(job: dict[str, Any], company: str, via: str, lang: str = "zh") -> dict[str, Any]:
    tx = _TEXT["en" if lang == "en" else "zh"]
    return {"category": "job_lead", "company": company,
            "position": job["title"], "location": job.get("location") or "",
            "comp_mentions": [], "urls": [job["url"]] if job.get("url") else [],
            "highlight": f"{tx[via]} {job.get('posted') or ''}".strip(),
            "suggested_next_step": tx["next"], "contact": {"channel": "careers"},
            "jd_excerpt": (job.get("jd") or "")[:2500], "target": True}


def _fill_jd(cfg, job: dict[str, Any], lead: dict[str, Any], lang: str) -> dict[str, Any]:
    """退路渠道的岗位没带正文——挑中了才去拉，拉不到不阻塞。"""
    from joblander import sourcing
    try:
        if job.get("mcf"):
            return sourcing.mcf_to_lead(job["mcf"], sourcing.mcf_job_detail(job["uid"][4:]), lang=lang) | {"target": True}
        if job.get("li_id"):
            d = sourcing.parse_linkedin_detail(sourcing._li_get(sourcing.LI_DETAIL.format(id=job["li_id"])))
            lead["jd_excerpt"] = (d.get("description") or "")[:2500]
    except Exception:
        pass
    return lead


# ---------- 主流程 ----------

def status_path(cfg) -> Path:
    return cfg.workspace_dir / "19-sourcing" / "targets-status.json"


def load_status(cfg) -> dict[str, Any]:
    return _load_json(status_path(cfg))


def source_targets(cfg, llm, days: int = 2, max_picks: int = MAX_PICKS,
                   only: list[str] | None = None) -> list[Path]:
    """每家目标公司：拉全部在招 → 地点筛 → 标题挑选 → 挑中的评分入池。各家互不拖累。
    days 只为与其它渠道同签名：目标公司看的是「全部在招里没看过的」，不按挂牌日期截。"""
    from joblander.scout import dedupe
    run = _Run(cfg, llm, "targets", days=36500)
    targets = [t for t in run.prefs.get("targets") or [] if not only or t in only]
    if not targets:
        return []
    locations = run.prefs.get("locations") or []
    cache = _load_json(_boards_path(cfg))
    status = load_status(cfg)
    for entry in targets:
        st: dict[str, Any] = {"ts": datetime.now(SGT).isoformat(timespec="seconds")}
        try:
            board, jobs = resolve(cfg, entry, cache)
            name = board.get("name") or entry
            st.update(name=name, ats=board.get("ats") or "")
            if board.get("ats"):
                st["board_url"] = ATS[board["ats"]]["board"].format(slug=board["slug"])
                via = "board"
            else:
                jobs = search_fallback(cfg, name, (locations or ["Singapore"])[0])
                via = "fallback"
            run.fetched += len(jobs or [])
            verdict = dedupe(run.rows, name, run.groups)
            if verdict.get("verdict") == "duplicate":
                st.update(total=len(jobs or []), tracked=verdict.get("existing"))
                status[entry] = st
                continue
            local = [j for j in jobs or [] if in_locations(j, locations)]
            fresh = [j for j in local if run.admit(j["uid"], "", name, j["title"])]
            later = fresh[MAX_TITLES:]
            fresh = fresh[:MAX_TITLES]
            for j in later:                        # 超出上限的不算看过，留给下一轮
                run.seen.pop(j["uid"], None)
            st.update(total=len(jobs or []), local=len(local), new=len(fresh))
            try:
                picks = screen_titles(cfg, llm, name, fresh, n=max_picks)
            except Exception:
                for j in fresh:                    # 挑选失败 → 这批不记账，下一轮重来
                    run.seen.pop(j["uid"], None)
                raise
            st["picked"] = len(picks)
            before = len(run.outs)
            for j in picks:
                lead = _fill_jd(cfg, j, to_lead(j, name, via, run.lang), run.lang)
                lead["company"] = name             # 统一用他写的名字（不是 SHOPEE IP SINGAPORE PTE LTD），建档也干净
                run.propose(lead, verdict, name, j["uid"].replace(":", "-"))
            st["proposed"] = len(run.outs) - before
            st["proposed_total"] = (status.get(entry) or {}).get("proposed_total", 0) + st["proposed"]
        except Exception as e:                      # noqa: BLE001
            st["error"] = str(e)[:200]
            run.log.append("sourcing.targets_error", "joblander.sourcing",
                           {"target": entry, "error": str(e)[:200]})
        status[entry] = st
    _save_json(_boards_path(cfg), cache)
    _save_json(status_path(cfg), {k: v for k, v in status.items()
                                  if k in (run.prefs.get("targets") or [])})
    return run.finish(targets)
