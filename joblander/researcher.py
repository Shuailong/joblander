"""Researcher 调研 — W2/W3/W4 的证据端（DESIGN §7.2 / ADR-16）。

单成员：尽调员 diligence()。边界不变——只产证据不下判断（判断归 Analyst）。
喂料与零输入是同一循环的两种起步（原调研员 research() 已并入，实战零使用）：
- 喂了料（URL / 贴入材料）：种子页打底，跳过开局盲扫，直接进覆盖判定
- 零输入：计划查询 → 首轮检索
之后同一 ReAct 循环：读材料摘录 → 判五项覆盖（动因/面试/技术栈/薪酬/稳定性）→
为缺口出新查询 → 死角止损，再综合成带编号来源的简介。
每条证据带来源与抓取日期（岗位信息会过期）；贴入材料按低可信级标注。
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from joblander.tz import LOCAL_TZ as SGT   # 单一来源，JOBLANDER_TZ 可覆盖

_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}


def _check_public_url(url: str) -> None:
    """只许 http(s) 且指向公网地址。

    抓取目标不完全受用户控制：mine_jd 吃的 Job URL 可能来自 LLM 对招聘邮件的抽取，
    尽调抓的是搜索引擎给的链接。不设限的话，一条构造过的链接就能让本地服务去
    拉内网地址或云元数据端点（169.254.169.254），抓回来的正文还会落成 JD 文件
    并进 LLM prompt。"""
    import ipaddress
    import socket

    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"只支持 http(s) 链接：{parts.scheme or url[:40]}")
    host = (parts.hostname or "").lower()
    if not host or host in _BLOCKED_HOSTS or host.endswith(".local"):
        raise ValueError(f"拒绝抓取非公网地址：{host or url[:40]}")
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except OSError as e:
        raise ValueError(f"域名解析失败：{host}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast):
            raise ValueError(f"拒绝抓取非公网地址：{host} → {ip}")


def fetch_url(url: str, timeout: int = 20) -> str:
    """公开页面抓取 → 保留块结构的 markdown 风格文本（登录态站点走浏览器人工贴入）。
    v0 曾把全部空白折叠成一整行——LLM 无所谓，人没法读（2026-08-11 JD 快照报障）。"""
    _check_public_url(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,zh;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    return _html_to_md(html)


def _html_to_md(html: str) -> str:
    """HTML → 可读文本：列表成 `- `、标题成 `##`、块级元素换行、实体解码。
    不追求完整 markdown（嵌套加粗/表格不管），只保住人读所需的块结构。"""
    from html import unescape
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
    html = re.sub(r"<br\s*/?\s*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<li[^>]*>", "\n- ", html, flags=re.IGNORECASE)
    html = re.sub(r"<h[1-6][^>]*>", "\n\n## ", html, flags=re.IGNORECASE)
    html = re.sub(r"</h[1-6]\s*>", "\n\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</?(p|div|ul|ol|section|article|table|tr|header|footer|main|nav)"
                  r"[^>]*>", "\n", html, flags=re.IGNORECASE)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    lines = (re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n"))
    lines = (ln for ln in lines if ln != "-")   # 空 li（图标/纯标签）不留光杆弹点
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


PLAN_SYSTEM = """你是调研规划员。给定目标公司（和可选上下文），输出用于 web 搜索的查询词。
输出严格 JSON：{"queries": ["4-5 个查询，中英混合"]}
必含两条固定查询（逐字，只替换公司名与限定词）：
①"<公司名> <行业限定词>"（主体查询）②"<公司名> engineering team tech stack"
其余 2-3 条覆盖：融资/规模/稳定性、招聘动因与岗位新闻、员工评价。
纪律：每条查询都带公司名；公司名有歧义（同名不同业）时全部查询加行业限定词。"""

REACT_SYSTEM = """你是尽调员（Diligence Agent），正在对目标公司做多轮检索尽调。
这是循环里的「看材料 → 判缺口 → 定下一轮」一步。

输入：目标公司、已跑过的查询（按轮）、已抓到的材料摘录（标题 + 来源级别 + 正文开头）。

五项覆盖目标——判断依据是**正文摘录**，标题相关但正文没讲到的不算覆盖：
①动因：为什么现在招这个岗（融资/扩张/新团队/战略转向的新闻信号）
②面试：面试流程与招聘体验 ③技术栈：工程团队与技术栈
④薪酬：band/层级数字 ⑤稳定性：裁员/融资断档/员工口碑

输出严格 JSON：
{"thought": "一句话：哪些已覆盖、哪些还缺、本轮打算怎么搜",
 "coverage": {"动因": "有|缺|死角", "面试": "…", "技术栈": "…", "薪酬": "…", "稳定性": "…"},
 "queries": ["最多 3 条新查询，只为标「缺」的项出"]}

纪律：
- 不重复已跑过的查询；同一项落空就换打法——中英互换、换关键词
  （interview process/面经、salary band/levels.fyi、funding/expansion/new team）、加行业限定词
- 某项已在两轮不同查询下仍缺 → 标「死角」，不再为它烧预算
- 五项全为「有」或「死角」→ queries 返回空数组（收兵）
- 每条查询带公司名；公司名有歧义（同名不同业）时加行业限定词"""

SYNTH_SYSTEM = """你是求职作战系统的尽调员，正在写综合简介。输入三部分：目标公司、求职者战况（仅供第四段参考）、多份带编号的材料（检索所得或人工喂入）。

先读材料再写。与目标公司无关的材料（同名不同业务的公司、无关网页）直接忽略：
不引用、不计入任何字段，把其编号放进 irrelevant 数组（内部记账，不写进 gaps）。

写四段综合简介（markdown，每段以粗体小标题开头，直接从第一段正文写起，不要任何前言或复述要求）：
**这家公司是谁** 业务、规模、稳定性。数字写明口径（总量与子口径分开给出）；
  不同来源对同一指标数字矛盾时，并列写出并各标来源，不许静默取一。
**为什么现在招这个岗** 招聘动因信号（扩张/新团队/战略转向/给谁配人）置顶展开——全文最重要的一段；
  材料查不到就明写「动因未查到（材料范围内）」。
**工程与技术侧** 技术栈、工程团队、工作方式，具体到工具与做法；只有定性说法就标注「仅定性」。
**对你意味着什么** 结合战况给具体判断：哪张牌该打、面试里该追问什么；
  材料里有面试流程/面经信号必须在本段引用。禁止空泛结语
  （「适合对 X 感兴趣的专业人士」「提供了良好的机会/平台」句式不许出现）。

引用纪律：
- 每个具体断言标来源编号如 [1][3]；标「（搜索摘要）」的材料按摘要级可信度措辞
- 求职者战况不是材料：不得写入 facts / salary_signals / risks，不得作为任何事实的来源；
  第四段确需引用战况时写「（你的战况）」，不写「[用户输入]」
- salary_signals 收录材料里一切薪酬数字；正文只写与目标岗位/职级相关的（带来源编号），
  无关岗位与全站均薪类聚合数字最多合并一句带过（「聚合站另有其他岗位区间，见档案」）——
  相关信号不许静默丢弃，无关数字不许刷屏稀释可读性

输出严格 JSON（中文，专名保留原文）：
{
  "summary_md": "上述四段",
  "card": ["3-5 行、每行 ≤40 字的 30 秒要点，顺序固定：这家是谁（规模+稳定性一句）→
            为什么现在招 → 你该打的主牌 → 最大红旗（没有就写最需当面核实的一项）→
            面试最该追问的一件事。只许压缩四段里已有的内容，不得引入四段没有的事实；
            行首不带序号、不带引用编号；禁空话与形容词堆砌"],
  "facts": [{"claim": "一句陈述（仅来自带编号材料）", "category": "funding|stability|product|tech_stack|org|comp|process|other",
             "source": "[编号] 域名", "confidence": "high|medium|low"}],
  "salary_signals": ["仅来自带编号材料的薪酬数字/结构，逐字——战况里的数字不算"],
  "risks": ["只写这家公司特有的风险（裁员记录/融资断档/具体差评/监管处罚/关键人离职）；
             写不出就返回空数组——「市场波动」「对技术要求高」这类话不许写"],
  "gaps": ["仍然没查到的关键信息——写给用户看的下一步，内部记账不放这里"],
  "irrelevant": [7, 12]
}"""

_SKIP_DOMAINS = ("linkedin.com", "glassdoor.com", "facebook.com", "instagram.com",
                 "youtube.com", "x.com", "twitter.com")

_TRUSTED_HOSTS = ("wikipedia.org", "bloomberg.com", "reuters.com", "ft.com", "fnlondon.com",
                  "techcrunch.com", "businesstimes.com.sg", "straitstimes.com",
                  "techinasia.com", "crunchbase.com", "privateequityinternational.com",
                  "efinancialcareers.com", "channelnewsasia.com")


def source_tier(url: str, company: str) -> str:
    """来源分级：official（公司自家域名）/ trusted（权威媒体与百科）/ aggregator（其余）。"""
    host = (url.split("/")[2] if "://" in url else url).lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", company.lower()) if len(t) >= 4]
    if any(t in host for t in tokens):
        return "official"
    if any(h in host for h in _TRUSTED_HOSTS):
        return "trusted"
    return "aggregator"


_TIER_LABEL = {"official": "官方一手", "trusted": "权威来源", "aggregator": "聚合站·低可信",
               "fed": "人工喂入·未经核实", "mcf": "MCF·官方挂牌"}


def _mcf_salary_page(company: str, position: str = "") -> dict[str, str] | None:
    """MCF 结构化薪酬证据页：该公司在招岗位 + 挂牌薪资区间。
    五项覆盖里「薪酬」最常死角——通用搜索抓不到新加坡 band，政府挂牌是最硬的一手。
    搜不到该公司的岗（或 MCF 不可用）返回 None，尽调照常走检索。"""
    from joblander.sourcing import mcf_search
    try:
        jobs = mcf_search(company, limit=16, timeout=10)
    except Exception:
        return None
    base = company.split("（")[0].strip().casefold()
    rows: list[tuple[str, str, str]] = []
    for j in jobs:
        co = ((j.get("postedCompany") or {}).get("name") or "")
        if base not in co.casefold():        # 全文搜索会混进别家的岗，按发布公司过滤
            continue
        s = j.get("salary") or {}
        cycle = ((s.get("type") or {}).get("salaryType") or "Monthly")
        sal = (f"{s['minimum']}–{s['maximum']} SGD/{cycle}"
               if s.get("minimum") and s.get("maximum") else "薪资未挂")
        rows.append((j.get("title") or "", sal,
                     (j.get("metadata") or {}).get("newPostingDate") or ""))
    if not rows:
        return None
    if position:                              # 目标岗位相近的排前面
        toks = [t for t in re.findall(r"[a-z]+", position.casefold()) if len(t) >= 4]
        rows.sort(key=lambda r: -sum(t in r[0].casefold() for t in toks))
    lines = "\n".join(f"- {t}：{sal}（挂牌 {d}）" for t, sal, d in rows[:12])
    return {"url": ("https://www.mycareersfuture.gov.sg/search?search="
                    + urllib.parse.quote(company)),
            "title": f"MCF 在招岗位与挂牌薪资（{len(rows)} 条）",
            "text": ("MyCareersFuture 官方挂牌（结构化数字，按岗位逐条；"
                     "挂牌为月薪区间，不是总包）：\n" + lines),
            "tier": "mcf"}


def _page_tier(p: dict[str, str], company: str) -> str:
    """页面级 tier：贴入材料显式标 fed；喂入 URL 按域名正常分级（官网喂进来仍是官方一手）。"""
    return p.get("tier") or source_tier(p["url"], company)


def diligence(cfg, llm, company: str, context: str = "", jd_text: str = "",
              max_pages: int = 8, max_rounds: int = 3,
              seed_urls: list[str] | None = None,
              seed_materials: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """尽调员：喂料或零输入起步 → ReAct 多轮补缺 → 综合简介（带编号来源）。

    喂了料（seed_urls 抓全文 / seed_materials 直接入料）：种子页打底，跳过计划轮
    与开局盲扫——缺什么由覆盖判定自己决定去搜；零输入：计划查询 → 首轮检索。
    循环每轮读材料摘录判五项覆盖（动因/面试/技术栈/薪酬/稳定性），为缺口出新查询；
    重复查询滤掉、连续落空标死角、搜不到新页止损。轨迹落 dossier["trail"]。
    产出：dossier dict（含 summary_md + sources），落 14-dossiers/<slug>.json
    （评估匹配自动引用 facts）。搜索不可用时抛 SearchError。
    """
    from joblander.scribe import _strip_fences
    from joblander.search import web_search

    def _norm_u(u: str) -> str:
        return u.rstrip("/").split("#")[0]

    def _hit_pages(qs: list[str], budget: int) -> list[dict[str, str]]:
        hits: list[dict[str, str]] = []
        seen_urls = {_norm_u(p["url"]) for p in pages}
        for q in qs:
            try:
                results = web_search(cfg, q, max_results=4)
            except Exception:
                continue
            for r in results:
                u = r["url"]
                host = u.split("/")[2] if "://" in u else u
                if _norm_u(u) in seen_urls or any(d in host for d in _SKIP_DOMAINS):
                    continue
                seen_urls.add(_norm_u(u))
                text = ""
                try:
                    text = fetch_url(u)[:6000]
                except Exception:
                    text = ""
                title = r["title"]
                if len(text) < 400:            # 登录墙/空壳页：退回搜索引擎的正文摘要
                    if len(r.get("snippet") or "") < 80:
                        continue
                    text, title = r["snippet"], f"{title}（搜索摘要）"
                hits.append({"url": u, "title": title, "text": text})
                if len(hits) >= budget:
                    return hits
        return hits

    prev: dict[str, Any] = {}
    from joblander.company import dossier_path
    prev_path = dossier_path(cfg, company)
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    # 喂入种子：URL 抓全文按域名正常分级；贴入材料标 fed（低可信）。失败如实记录，不吞
    pages: list[dict[str, str]] = []
    seed_fail: list[str] = []
    for u in (seed_urls or []):
        try:
            text = fetch_url(u)[:6000]
        except Exception:
            text = ""
        if len(text) >= 400:
            host = u.split("/")[2] if "://" in u else u
            pages.append({"url": u, "title": f"{host}（喂入）", "text": text})
        else:
            seed_fail.append(u)
    for i, m in enumerate(seed_materials or []):
        if (m.get("text") or "").strip():
            pages.append({"url": "", "title": m.get("label") or f"贴入材料 {i + 1}",
                          "text": m["text"][:15000], "tier": "fed"})
    seeded = bool(pages)

    pinned = 0
    # 抗波动：上轮 official/trusted 来源钉住重抓——一旦进过档案的高价值来源不再靠搜索碰运气
    for ps in (prev.get("sources") or []):
        if ps.get("tier") not in ("official", "trusted") or pinned >= 4:
            continue
        try:
            text = fetch_url(ps["url"])[:6000]
        except Exception:
            continue
        if len(text) >= 400:
            pages.append({"url": ps["url"], "title": f"{ps.get('title', '')}（上轮钉住）",
                          "text": text})
            pinned += 1

    # MCF 结构化薪酬证据（不算喂料——零输入照样盲扫）：搜不到就算了，不阻塞
    pos = re.search(r"目标岗位：([^；;]+)", context or "")
    mcf = _mcf_salary_page(company, position=pos.group(1).strip() if pos else "")
    if mcf is not None:
        pages.append(mcf)

    queries: list[str] = []
    if not seeded:      # 零输入才需要计划轮 + 开局盲扫；喂了料，缺什么由覆盖判定去搜
        plan = json.loads(_strip_fences(llm.generate(
            f"目标公司：{company}\n上下文：{context or '（无）'}",
            system=PLAN_SYSTEM, json_mode=True)))
        queries = [q for q in (plan.get("queries") or [])[:5] if q.strip()]
        pages += _hit_pages(queries, max_pages)

    trail: list[dict[str, Any]] = []
    ran: list[list[str]] = [queries] if queries else []
    for rnd in range(1, max_rounds + 1) if pages else []:
        # ReAct：观察=正文摘录（不是标题清单——标题相关正文空壳的不算覆盖）
        digest = "\n".join(
            f"[{i+1}]（{_TIER_LABEL[_page_tier(p, company)]}）{p['title']}\n"
            f"    {p['text'][:400]}" for i, p in enumerate(pages))
        hist_q = ("\n".join(f"R{i}: {'; '.join(qs)}" for i, qs in enumerate(ran))
                  or "（尚未检索——起步材料全部来自喂入）")
        try:
            act = json.loads(_strip_fences(llm.generate(
                f"公司：{company}\n\n已跑过的查询：\n{hist_q}\n\n"
                f"材料摘录：\n{digest[:24000]}",
                system=REACT_SYSTEM, json_mode=True)))
        except Exception:
            break
        done_q = {q for qs in ran for q in qs}
        qs = [q for q in (act.get("queries") or [])[:3]
              if q.strip() and q not in done_q]
        step: dict[str, Any] = {"round": rnd, "thought": (act.get("thought") or "")[:200],
                                "coverage": act.get("coverage") or {},
                                "queries": qs, "gained": 0}
        trail.append(step)
        if not qs:                              # 收兵：全覆盖/全死角（重复查询也在此滤停）
            break
        before = len(pages)
        pages += _hit_pages(qs, 4)
        ran.append(qs)
        step["gained"] = len(pages) - before
        if step["gained"] == 0:                 # 空转：换了措辞也捞不到新页，止损
            break

    if not pages:
        hint = (f"；喂入的 {len(seed_fail)} 条链接全数抓取失败（登录墙站点请复制正文贴入）"
                if seed_fail else "")
        raise RuntimeError(f"尽调员一页材料都没拿到（{company}）——"
                           f"搜索被限流或全是登录墙{hint}")

    corpus = "\n\n".join(
        f"=== 材料 [{i+1}]（{_TIER_LABEL[_page_tier(p, company)]}）"
        f"{p['title']}（{p['url'] or '贴入原文，无链接'}）===\n{p['text']}"
        for i, p in enumerate(pages))
    if jd_text:    # JD 是「为什么现在招这个岗」的一手来源：团队/职责/动因线索
        corpus += ("\n\n=== 材料 [JD] 岗位 JD（本地档案，一手来源）——"
                   "『为什么现在招这个岗』优先从此提取，引用标 [JD] ===\n"
                   + jd_text[:8000])
    hist = [f"- {f.get('claim')}（{f.get('source', '')}）"
            for f in (prev.get("facts") or []) if f.get("confidence") == "high"][:20]
    if hist:    # 上轮存档进语料：summary 才能延续历史信号；矛盾时按口径纪律并列
        corpus += (f"\n\n=== 上轮调研存档（{prev.get('fetched_at', '')}，已确认事实，"
                   f"引用时注明「上轮调研」；与本轮材料数字矛盾时并列写出）===\n"
                   + "\n".join(hist))
    dossier = json.loads(_strip_fences(llm.generate(
        f"公司：{company}\n求职者战况：{context or '（未提供）'}\n\n{corpus[:150000]}",
        system=SYNTH_SYSTEM, json_mode=True)))
    dossier["company"] = company
    dossier["fetched_at"] = datetime.now(SGT).strftime("%Y-%m-%d")
    dossier["mode"] = "deep"
    dossier["jd_used"] = bool(jd_text)
    dossier["trail"] = trail
    dossier["sources"] = [{"n": i + 1, "title": p["title"], "url": p["url"],
                           "tier": _page_tier(p, company)}
                          for i, p in enumerate(pages)]
    dossier["source_labels"] = [p["url"] or p["title"] for p in pages]
    if seeded or seed_fail:
        dossier["seeded"] = {
            "urls": [p["url"] for p in pages if p["url"] and "（喂入）" in p["title"]],
            "materials": [p["title"] for p in pages if p.get("tier") == "fed"],
            "failed_urls": seed_fail}

    out = dossier_path(cfg, company, for_write=True)   # 写一律用规范 slug
    out.parent.mkdir(parents=True, exist_ok=True)
    if prev:
        new_claims = {f.get("claim", "") for f in dossier.get("facts") or []}
        carried = [{**f, "carried_from": prev.get("fetched_at", "")}
                   for f in (prev.get("facts") or [])
                   if f.get("claim") and f["claim"] not in new_claims
                   and f.get("confidence") == "high"][:20]
        dossier["facts"] = (dossier.get("facts") or []) + carried
        new_sigs = set(dossier.get("salary_signals") or [])
        dossier["salary_signals"] = sorted(new_sigs | {
            s for s in (prev.get("salary_signals") or []) if s})
        dossier["previous_facts"] = (prev.get("facts") or [])[:50]
    out.write_text(json.dumps(dossier, ensure_ascii=False, indent=1), encoding="utf-8")

    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "dossier.diligence", "agent:diligence",
        {"company": company, "pages": len(pages), "rounds": len(trail),
         "seeds": len(dossier.get("seeded", {}).get("urls", []))
                  + len(dossier.get("seeded", {}).get("materials", [])),
         "facts": len(dossier.get("facts", [])), "out": str(out)})
    return dossier


def format_deep_summary(dossier: dict[str, Any]) -> str:
    """尽调结果 → 落时间线的 markdown。展示层三条纪律：
    ①来源只列简介实际引用的（全量存 dossier 供审计）②编号按正文出现顺序
    重排为连续 1..k（正文引用同步重映射）③内部记账（无关材料等）不上屏。
    尽调轨迹（每轮缺什么/搜什么/捞到几页）附在末尾——未查到的项能看到不是没试。"""
    md = (dossier.get("summary_md") or "").strip()
    order: list[int] = []
    for n in re.findall(r"\[(\d+)\]", md):
        if int(n) not in order:
            order.append(int(n))
    remap = {old: i + 1 for i, old in enumerate(order)}
    md = re.sub(r"\[(\d+)\]",
                lambda m: f"[{remap[int(m.group(1))]}]" if int(m.group(1)) in remap
                else m.group(0), md)
    mark = {"official": " 🏢官网", "trusted": "", "aggregator": " ⚠️聚合站",
            "fed": " 📎人工喂入", "mcf": " 🏛️MCF挂牌"}
    lines = []
    card = [re.sub(r"^[①-⑩\s]+", "", re.sub(r"\s*\[\d+\]", "", str(c))).strip()
            for c in dossier.get("card") or [] if str(c).strip()]   # 剥引用编号与行首序号
    if card:
        lines += ["**30 秒要点**", ""] + [f"- {c}" for c in card[:5]] + ["", "---", ""]
    lines += [md, "", f"**来源**（{len(order)} 个）", ""]
    if dossier.get("jd_used") and "[JD]" in md:
        lines.append("- JD. 岗位 JD（本地档案）")
    by_n = {s["n"]: s for s in dossier.get("sources") or []}
    for old in order:
        s = by_n.get(old)
        if not s:
            continue
        title = (s.get("title") or s["url"]).replace("（上轮钉住）", "").strip()
        link = f"[{title}]({s['url']})" if s.get("url") else title
        lines.append(f"{remap[old]}. {link}{mark.get(s.get('tier', ''), '')}")
    gaps = [g for g in (dossier.get("gaps") or [])
            if not re.search(r"材料\s*\[?\d*\]?.{0,8}无关", g)]
    if gaps:
        lines += ["", "**未查到（下一步）**"] + [f"- {g}" for g in gaps]
    failed = (dossier.get("seeded") or {}).get("failed_urls") or []
    if failed:
        lines += ["", "**喂入链接抓取失败**（登录墙请复制正文贴入重跑）"] + [f"- {u}" for u in failed]
    trail = dossier.get("trail") or []
    if trail:
        lines += ["", f"**尽调轨迹**（计划轮 + {len(trail)} 判读轮）"]
        for s in trail:
            cov = s.get("coverage") or {}
            miss = [k for k, v in cov.items() if v == "缺"]
            dead = [k for k, v in cov.items() if v == "死角"]
            head = "；".join(filter(None, [
                "缺 " + "、".join(miss) if miss else "",
                "死角 " + "、".join(dead) if dead else ""])) or "五项覆盖"
            tail = (f" → {len(s['queries'])} 查询 → +{s.get('gained', 0)} 页"
                    if s.get("queries") else " → 收兵")
            lines.append(f"- R{s.get('round')}：{head}{tail}")
    return "\n".join(lines)
