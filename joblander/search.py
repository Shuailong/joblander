"""Web 搜索抽象 — 尽调员的眼睛（Researcher 域工具）。

现实（2026-08 实测）：DDG（html/lite）、Bing、Mojeek、SearxNG 公共实例对无 JS
爬虫全面反爬——零 key 的 HTML 抓取路线已死。搜索走 API，key 自备（config
`search:` 段或环境变量，永远不落代码）：

  provider: tavily   + api_key            —— 专为 LLM agent，免费档即够（推荐）
  provider: brave    + api_key            —— Brave Search API
  provider: google   + api_key + cx       —— Google CSE（免费 100 次/天）
  未配置                                   —— 仍会试 DDG（大概率被拦），失败报错引导配 key

纪律：搜索失败明说（SearchError），不静默返回空——调用方自行降级到人工给料。
"""

from __future__ import annotations

import html as _html
import json
import re
import urllib.parse
import urllib.request
from typing import Any


class SearchError(RuntimeError):
    pass


def _http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) joblander-research"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _ddg_search(query: str, max_results: int = 6) -> list[dict[str, str]]:
    """DuckDuckGo HTML 版结果页解析。链接藏在 uddg= 参数里，需二次解码。"""
    page = _http_get("https://html.duckduckgo.com/html/?q="
                     + urllib.parse.quote(query))
    out: list[dict[str, str]] = []
    # 两段式：result__a 定结果块边界，snippet 只在本块区间内找（可选组配懒惰匹配会永远走空）
    a_pat = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                       re.DOTALL)
    sn_pat = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
    anchors = list(a_pat.finditer(page))
    for i, m in enumerate(anchors):
        href, title = m.group(1), m.group(2)
        seg_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(page)
        sn = sn_pat.search(page, m.end(), seg_end)
        uddg = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg")
        url = urllib.parse.unquote(uddg[0]) if uddg else href
        if not url.startswith("http"):
            continue
        out.append({"title": _strip_tags(title), "url": url,
                    "snippet": _strip_tags(sn.group(1) if sn else "")[:300]})
        if len(out) >= max_results:
            break
    return out


def _google_cse(query: str, api_key: str, cx: str,
                max_results: int = 6) -> list[dict[str, str]]:
    params = urllib.parse.urlencode({"key": api_key, "cx": cx, "q": query,
                                     "num": min(max_results, 10)})
    data = json.loads(_http_get(f"https://www.googleapis.com/customsearch/v1?{params}"))
    return [{"title": i.get("title", ""), "url": i.get("link", ""),
             "snippet": i.get("snippet", "")}
            for i in data.get("items", [])][:max_results]


def _strip_tags(s: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _tavily(query: str, api_key: str, max_results: int = 6) -> list[dict[str, str]]:
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps({"api_key": api_key, "query": query,
                         "max_results": max_results}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": (r.get("content") or "")[:800]}
            for r in data.get("results", [])][:max_results]


def _brave(query: str, api_key: str, max_results: int = 6) -> list[dict[str, str]]:
    params = urllib.parse.urlencode({"q": query, "count": min(max_results, 20)})
    req = urllib.request.Request(
        f"https://api.search.brave.com/res/v1/web/search?{params}",
        headers={"X-Subscription-Token": api_key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": _strip_tags(r.get("description", ""))[:300]}
            for r in (data.get("web") or {}).get("results", [])][:max_results]


NO_KEY_HINT = ("内置零 key 引擎已被各家反爬拦截（2026-08 实测）。"
               "到 tavily.com 注册免费 key（约 1 分钟），config.yaml 加：\n"
               "search:\n  provider: tavily\n  api_key: tvly-…")


def _one_provider(pv: dict, query: str, max_results: int) -> list[dict[str, str]]:
    name, key = pv.get("provider") or "", pv.get("api_key") or ""
    if name == "tavily" and key:
        return _tavily(query, key, max_results)
    if name == "brave" and key:
        return _brave(query, key, max_results)
    if name == "google" and key and pv.get("cx"):
        return _google_cse(query, key, pv["cx"], max_results)
    raise SearchError(f"provider 配置不完整：{name or '（空）'}")


def _providers(cfg) -> list[dict]:
    """config 的 search 段：providers 列表（多引擎并行）或单 provider 字段（向后兼容）。"""
    import os
    sc = (cfg.raw.get("search") or {}) if cfg is not None else {}
    if sc.get("providers"):
        return list(sc["providers"])
    key = sc.get("api_key") or os.environ.get("SEARCH_API_KEY") or ""
    return [{**sc, "api_key": key}] if sc.get("provider") and key else []


def web_search(cfg, query: str, max_results: int = 6) -> list[dict[str, str]]:
    """统一入口。配了多个 provider 时并行查询、按 URL 去重、交错合并（覆盖面优先）；
    任一 provider 成功即可用；全灭才抛 SearchError。无任何 key 时试 DDG（大概率被拦）。"""
    pvs = _providers(cfg)
    if not pvs:
        try:
            out = _ddg_search(query, max_results)
        except Exception as e:
            raise SearchError(f"搜索失败（{query}）：{e}\n{NO_KEY_HINT}") from e
        if not out:
            raise SearchError(f"DDG 无结果（疑似反爬拦截）。{NO_KEY_HINT}")
        return out

    if len(pvs) == 1:
        try:
            return _one_provider(pvs[0], query, max_results)
        except SearchError:
            raise
        except Exception as e:
            raise SearchError(f"搜索失败（{query}）：{e}") from e

    from concurrent.futures import ThreadPoolExecutor
    batches: list[list[dict[str, str]]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=len(pvs)) as ex:
        futs = {ex.submit(_one_provider, pv, query, max_results): pv for pv in pvs}
        for f, pv in futs.items():
            try:
                batches.append(f.result(timeout=25))
            except Exception as e:
                errors.append(f"{pv.get('provider')}: {e}")
    if not batches:
        raise SearchError(f"全部 provider 失败（{query}）：{'；'.join(errors)[:300]}")
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for i in range(max(len(b) for b in batches)):    # 交错取各引擎第 i 名 → 结果多样性
        for b in batches:
            if i < len(b) and b[i]["url"] not in seen:
                seen.add(b[i]["url"])
                merged.append(b[i])
    return merged[:max_results * 2]
