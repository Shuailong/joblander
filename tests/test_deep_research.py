"""尽调员（Diligence Agent）：搜索抽象 + 零输入 ReAct 多轮尽调端到端。"""

from __future__ import annotations

import json

import pytest

from joblander.config import Config
from joblander.llm import MockLLM
from joblander.search import SearchError, _ddg_search, web_search

DDG_HTML = """
<div class="result">
<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Facme.ai%2Fabout&amp;rut=x">Acme AI — About <b>us</b></a>
<a class="result__snippet" href="#">Acme builds <b>agent</b> platforms.</a>
</div>
<div class="result">
<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fnews.site%2Facme-round&amp;rut=y">Acme raises $30M</a>
</div>
"""


def test_ddg_parse(monkeypatch):
    monkeypatch.setattr("joblander.search._http_get", lambda url, timeout=15: DDG_HTML)
    out = _ddg_search("acme ai")
    assert out[0]["url"] == "https://acme.ai/about"
    assert out[0]["title"] == "Acme AI — About us"          # 标签剥掉、实体解码
    assert "agent platforms" in out[0]["snippet"]
    assert out[1]["url"] == "https://news.site/acme-round"


def test_web_search_provider_switch(monkeypatch):
    calls = {}

    def fake_get(url, timeout=15):
        calls["url"] = url
        if "customsearch" in url:
            return json.dumps({"items": [{"title": "t", "link": "https://x.y", "snippet": "s"}]})
        return DDG_HTML
    monkeypatch.setattr("joblander.search._http_get", fake_get)

    class C:
        raw = {"search": {"provider": "google", "api_key": "k", "cx": "c"}}
    assert web_search(C(), "q")[0]["url"] == "https://x.y"
    assert "customsearch" in calls["url"]

    class C2:
        raw = {}
    assert web_search(C2(), "q")[0]["url"].startswith("https://acme.ai")


def test_web_search_error(monkeypatch):
    def boom(url, timeout=15):
        raise OSError("net down")
    monkeypatch.setattr("joblander.search._http_get", boom)

    class C:
        raw = {}
    with pytest.raises(SearchError):
        web_search(C(), "q")


@pytest.fixture
def cfg(tmp_path):
    ws = tmp_path / "ws"
    (ws / "08-events").mkdir(parents=True)
    return Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")


@pytest.fixture(autouse=True)
def _mcf_offline(monkeypatch):
    """测试不触网：MCF 缺省当不可用（专测 MCF 的用例自己再打桩覆盖）。"""
    def down(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr("joblander.sourcing.mcf_search", down)


PAGES = {
    "https://acme.ai/about": "Acme AI builds enterprise agent platforms. " * 40,
    "https://news.site/acme-round": "Acme raised a $30M Series B led by Foo Capital. " * 30,
    "https://blocked.linkedin.com/acme": "login wall " * 100,
    "https://thin.page/x": "too short",
    "https://eng.blog/acme-stack": "Their stack: Python, K8s, vector DB. " * 30,
}


def test_diligence_end_to_end(cfg, monkeypatch):
    """规划→搜索→抓取（跳过登录墙域名/短正文）→ReAct 补缺→综合，dossier 带来源与轨迹。"""
    searched: list[str] = []

    def fake_search(c, q, max_results=4):
        searched.append(q)
        if "stack" in q:
            return [{"title": "Eng blog", "url": "https://eng.blog/acme-stack", "snippet": ""}]
        return [{"title": "About", "url": "https://acme.ai/about", "snippet": ""},
                {"title": "LI", "url": "https://blocked.linkedin.com/acme", "snippet": ""},
                {"title": "Thin", "url": "https://thin.page/x", "snippet": ""},
                {"title": "News", "url": "https://news.site/acme-round", "snippet": ""}]
    monkeypatch.setattr("joblander.search.web_search", fake_search)
    monkeypatch.setattr("joblander.researcher.fetch_url", lambda u, timeout=20: PAGES[u])

    llm = MockLLM([
        json.dumps({"queries": ["Acme AI company", "Acme AI funding"]}),
        json.dumps({"thought": "融资已覆盖，缺技术栈",                    # R1：为缺口出查询
                    "coverage": {"动因": "有", "面试": "死角", "技术栈": "缺",
                                 "薪酬": "死角", "稳定性": "有"},
                    "queries": ["Acme AI tech stack"]}),
        json.dumps({"thought": "技术栈已补到，其余死角",                  # R2：收兵
                    "coverage": {"动因": "有", "面试": "死角", "技术栈": "有",
                                 "薪酬": "死角", "稳定性": "有"},
                    "queries": []}),
        json.dumps({"summary_md": "Acme 是企业 agent 平台公司 [1]，B 轮 $30M [2]，栈为 Python/K8s [3]。",
                    "card": ["企业 agent 平台，B 轮 $30M [2]", "扩张期招人"],
                    "facts": [{"claim": "Series B $30M", "category": "funding",
                               "source": "[2] news.site", "confidence": "high"}],
                    "salary_signals": [], "risks": [], "gaps": ["薪酬 band 未知"]}),
    ])
    from joblander.researcher import diligence, format_deep_summary
    d = diligence(cfg, llm, "Acme AI")
    assert d["mode"] == "deep" and d["fetched_at"]
    urls = [s["url"] for s in d["sources"]]
    assert "https://blocked.linkedin.com/acme" not in urls        # 登录墙域名跳过
    assert "https://thin.page/x" not in urls                      # 短正文丢弃
    assert "https://eng.blog/acme-stack" in urls                  # ReAct 轮补到了
    assert any("stack" in q for q in searched)
    assert len(d["trail"]) == 2 and d["trail"][0]["gained"] == 1  # 轨迹落档
    assert "正文" in llm.calls[1]["system"] or "摘录" in llm.calls[1]["prompt"]
    assert "Python, K8s" not in llm.calls[1]["prompt"]            # R1 时页还没抓
    assert (cfg.workspace_dir / "14-dossiers" / "Acme-AI.json").exists()
    md = format_deep_summary(d)
    assert "[Eng blog](https://eng.blog/acme-stack)" in md        # 编号来源链接
    assert "薪酬 band 未知" in md
    assert "尽调轨迹" in md and "缺 技术栈" in md and "收兵" in md
    assert md.index("30 秒要点") < md.index("Acme 是企业")      # 要点卡置顶
    assert "- 企业 agent 平台，B 轮 $30M\n" in md               # 卡内引用编号剥掉（正文保留）


def test_diligence_no_pages(cfg, monkeypatch):
    """一页都抓不到：明确报错，不产出空档案；喂入链接全挂时提示改贴正文。"""
    monkeypatch.setattr("joblander.search.web_search",
                        lambda c, q, max_results=4: [])
    llm = MockLLM([json.dumps({"queries": ["q1"]})])
    from joblander.researcher import diligence
    with pytest.raises(RuntimeError, match="登录墙"):
        diligence(cfg, llm, "Ghost Co")
    assert not (cfg.workspace_dir / "14-dossiers" / "Ghost-Co.json").exists()

    def dead(u, timeout=20):
        raise OSError("404")
    monkeypatch.setattr("joblander.researcher.fetch_url", dead)
    # 种子全挂 → 退回零输入路径继续（计划轮照跑）；搜索也空才报错，且点名喂入失败
    with pytest.raises(RuntimeError, match="喂入的 1 条链接全数抓取失败"):
        diligence(cfg, MockLLM([json.dumps({"queries": ["q1"]})]),
                  "Ghost Co", seed_urls=["https://dead.link/x"])


def test_diligence_seeded_skips_blind_scan(cfg, monkeypatch):
    """喂料起步（ADR-16）：种子打底跳过计划轮与盲扫——URL 按域名正常分级、
    贴入材料标 fed 低可信；缺口照常补搜；坏链接如实入档不吞。"""
    searched: list[str] = []

    def fake_search(c, q, max_results=4):
        searched.append(q)
        return [{"title": "News", "url": "https://news.site/acme-round", "snippet": ""}]
    monkeypatch.setattr("joblander.search.web_search", fake_search)

    def fake_fetch(u, timeout=20):
        if "dead.link" in u:
            raise OSError("404")
        return PAGES.get(u, "fallback page body. " * 40)
    monkeypatch.setattr("joblander.researcher.fetch_url", fake_fetch)

    llm = MockLLM([
        json.dumps({"thought": "种子覆盖动因技术栈，缺稳定性",              # 直接判读，无计划轮
                    "coverage": {"稳定性": "缺"}, "queries": ["Acme AI funding"]}),
        json.dumps({"thought": "补到", "coverage": {"稳定性": "有"}, "queries": []}),
        json.dumps({"summary_md": "**这家公司是谁** x [1]。群聊说在招 [2]。融资 [3]。",
                    "facts": [], "salary_signals": [], "risks": [], "gaps": []}),
    ])
    from joblander.researcher import diligence, format_deep_summary
    d = diligence(cfg, llm, "Acme AI",
                  seed_urls=["https://acme.ai/about", "https://dead.link/x"],
                  seed_materials=[{"label": "群聊贴入", "text": "Acme 在招 agent 平台工程师。" * 30}])
    assert len(llm.calls) == 3                                  # 判读×2 + synth——没有计划轮
    assert "规划" not in (llm.calls[0]["system"] or "")
    assert searched == ["Acme AI funding"]                      # 只为缺口搜，无开局盲扫
    assert "尚未检索——起步材料全部来自喂入" in llm.calls[0]["prompt"]
    assert "人工喂入" in llm.calls[0]["prompt"]                  # fed 级别进判读摘录

    tiers = {s["title"]: s["tier"] for s in d["sources"]}
    assert tiers["acme.ai（喂入）"] == "official"                # 喂入官网仍是官方一手
    assert tiers["群聊贴入"] == "fed"
    assert d["seeded"] == {"urls": ["https://acme.ai/about"],
                           "materials": ["群聊贴入"],
                           "failed_urls": ["https://dead.link/x"]}
    md = format_deep_summary(d)
    assert "[acme.ai（喂入）](https://acme.ai/about)" in md
    assert "2. 群聊贴入 📎人工喂入" in md                        # 无链接来源不渲染成空链接
    assert "喂入链接抓取失败" in md and "https://dead.link/x" in md


def test_diligence_react_dedup_stops_loop(cfg, monkeypatch):
    """重复查询滤停：第二判读轮只出已跑过的查询 → 滤空即收兵，不再烧搜索。"""
    searched: list[str] = []

    def fake_search(c, q, max_results=4):
        searched.append(q)
        if "interview" in q:
            return [{"title": "面经", "url": "https://forum.example/acme-iv", "snippet": ""}]
        return [{"title": "About", "url": "https://acme.ai/about", "snippet": ""}]
    monkeypatch.setattr("joblander.search.web_search", fake_search)
    monkeypatch.setattr("joblander.researcher.fetch_url",
                        lambda u, timeout=20: "Acme interview rounds detail. " * 40)

    llm = MockLLM([
        json.dumps({"queries": ["Acme AI"]}),
        json.dumps({"thought": "缺面试", "coverage": {"面试": "缺"},
                    "queries": ["Acme interview process"]}),
        json.dumps({"thought": "还想搜面试", "coverage": {"面试": "缺"},
                    "queries": ["Acme interview process"]}),      # 与 R1 重复
        json.dumps({"summary_md": "**这家公司是谁** x [1]", "facts": [],
                    "salary_signals": [], "risks": [], "gaps": []}),
    ])
    from joblander.researcher import diligence
    d = diligence(cfg, llm, "Acme AI")
    assert searched.count("Acme interview process") == 1          # 重复查询没有二次执行
    assert len(d["trail"]) == 2 and d["trail"][1]["queries"] == []
    assert len(llm.calls) == 4                                    # plan + 2 判读 + synth


def test_diligence_react_futility_break(cfg, monkeypatch):
    """空转止损：补搜捞不到任何新页 → 循环立停，不再烧判读轮。"""
    monkeypatch.setattr("joblander.search.web_search", lambda c, q, max_results=4: [
        {"title": "About", "url": "https://acme.ai/about", "snippet": ""}])   # 永远同一页
    monkeypatch.setattr("joblander.researcher.fetch_url",
                        lambda u, timeout=20: "Acme AI platform. " * 40)
    llm = MockLLM([
        json.dumps({"queries": ["Acme AI"]}),
        json.dumps({"thought": "缺薪酬", "coverage": {"薪酬": "缺"},
                    "queries": ["Acme salary band"]}),
        json.dumps({"summary_md": "**这家公司是谁** x [1]", "facts": [],
                    "salary_signals": [], "risks": [], "gaps": []}),
    ])
    from joblander.researcher import diligence
    d = diligence(cfg, llm, "Acme AI", max_rounds=3)
    assert len(llm.calls) == 3            # plan + 1 判读 + synth——空转后没有第二判读轮
    assert d["trail"][0]["gained"] == 0


def test_web_search_tavily_and_brave(monkeypatch):
    """key 型 provider：tavily/brave 请求形态与解析。"""
    import urllib.request

    class FakeResp:
        def __init__(self, body): self.body = body.encode()
        def read(self): return self.body
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake_open(req, timeout=20):
        url = req.full_url
        if "tavily" in url:
            return FakeResp(json.dumps({"results": [
                {"title": "T", "url": "https://t.co/1", "content": "c" * 500}]}))
        if "brave" in url:
            assert req.headers.get("X-subscription-token") == "bk"
            return FakeResp(json.dumps({"web": {"results": [
                {"title": "B", "url": "https://b.co/1", "description": "<b>d</b>"}]}}))
        raise AssertionError(url)
    monkeypatch.setattr(urllib.request, "urlopen", fake_open)

    class CT:
        raw = {"search": {"provider": "tavily", "api_key": "tk"}}
    out = web_search(CT(), "q")
    assert out[0]["url"] == "https://t.co/1" and len(out[0]["snippet"]) == 500

    class CB:
        raw = {"search": {"provider": "brave", "api_key": "bk"}}
    out = web_search(CB(), "q")
    assert out[0] == {"title": "B", "url": "https://b.co/1", "snippet": "d"}


def test_web_search_no_key_hint(monkeypatch):
    """无 key 且 DDG 被拦（空结果）：报错必须带配 key 引导。"""
    monkeypatch.setattr("joblander.search._http_get",
                        lambda url, timeout=15: "<html>anomaly page</html>")

    class C:
        raw = {}
    with pytest.raises(SearchError, match="tavily.com"):
        web_search(C(), "q")


def test_summary_hard_checks_catch_violations():
    """金标硬检查：四段缺失/信号丢弃/空话/通用风险/无引用，逐项能抓。"""
    from evals.summary_eval import hard_checks
    bad = {"mode": "deep",
           "summary_md": "Acme 是一家公司，提供了良好的机会，适合对 AI 感兴趣的专业人士。",
           "salary_signals": ["Avg. Salary $125.2k"],
           "risks": ["市场波动带来的风险"],
           "sources": [{"n": 1, "url": "https://x.y", "title": "t"}]}
    v = hard_checks(bad)
    joined = " ".join(v)
    assert sum(1 for x in v if x.startswith("缺段落")) == 4
    assert "薪酬信号一条都没进简介" in joined
    assert "空话句式" in joined and "通用风险" in joined
    assert "缺 tier" in joined and "无任何编号引用" in joined
    assert "缺 30 秒要点卡" in joined


def test_summary_hard_checks_pass_good():
    from evals.summary_eval import hard_checks
    good = {"mode": "deep",
            "summary_md": ("**这家公司是谁**——总 AUM 48 亿美元，多策略基金 35 亿 [1]。\n"
                           "**为什么现在招这个岗**——给基金经理配 AI 专家 [8]。\n"
                           "**工程与技术侧**——仅定性，未见具体栈 [8]。均薪 $125.2k [11]。\n"
                           "**对你意味着什么**——面试里追问 AI 团队编制与 band。"),
            "salary_signals": ["Avg. Salary $125.2k",
                               "DevOps Junior 1 salaries S$7,150"],   # 无关岗位：可不上屏
            "card": ["48 亿美元多策略基金，稳定", "给基金经理配 AI 专家",
                     "主牌：生产级 LLM 链路", "红旗：band 未披露", "追问：AI 团队编制"],
            "risks": [],
            "sources": [{"n": 1, "url": "https://en.wikipedia.org/wiki/X",
                         "title": "X", "tier": "trusted"}]}
    assert hard_checks(good) == []          # 按岗位相关性筛信号合法，只禁全军覆没


def test_source_tier():
    from joblander.researcher import source_tier
    assert source_tier("https://www.heliosasia.com/join-us", "Helios Asia") == "official"
    assert source_tier("https://en.wikipedia.org/wiki/Helios_Asia", "Helios Asia") == "trusted"
    assert source_tier("https://campus.niuqizp.com/x", "Helios Asia") == "aggregator"


def test_summary_hard_checks_prompt_and_context_leak():
    """新违规项：prompt 指令抄进正文开头 / 战况引用写成 [用户输入]。"""
    from evals.summary_eval import hard_checks
    bad = {"mode": "deep",
           "summary_md": ("综合简介 markdown，固定四段：\n**这家公司是谁** x [1]\n"
                          "**为什么现在招这个岗** y [用户输入]\n**工程与技术侧** z\n"
                          "**对你意味着什么** w"),
           "salary_signals": [], "risks": [],
           "sources": [{"n": 1, "url": "https://x.y", "title": "t", "tier": "trusted"}]}
    joined = " ".join(hard_checks(bad))
    assert "prompt 指令泄漏" in joined and "战况引用格式违规" in joined


def test_multi_provider_parallel_merge(monkeypatch):
    """多引擎并行：交错合并、URL 去重、单引擎挂了不影响。"""
    import joblander.search as sm

    monkeypatch.setattr(sm, "_tavily", lambda q, k, n=6: [
        {"title": "t1", "url": "https://a.co", "snippet": ""},
        {"title": "t2", "url": "https://b.co", "snippet": ""}])
    def brave_boom(q, k, n=6):
        raise OSError("brave down")
    monkeypatch.setattr(sm, "_brave", brave_boom)

    class C:
        raw = {"search": {"providers": [
            {"provider": "tavily", "api_key": "tk"},
            {"provider": "brave", "api_key": "bk"}]}}
    out = sm.web_search(C(), "q")                       # brave 挂，tavily 独活
    assert [r["url"] for r in out] == ["https://a.co", "https://b.co"]

    monkeypatch.setattr(sm, "_brave", lambda q, k, n=6: [
        {"title": "b1", "url": "https://a.co", "snippet": ""},      # 与 tavily 重复
        {"title": "b2", "url": "https://c.co", "snippet": ""}])
    out = sm.web_search(C(), "q")
    urls = [r["url"] for r in out]
    assert set(urls) == {"https://a.co", "https://b.co", "https://c.co"}
    assert len(urls) == len(set(urls))                  # 去重
    assert urls[0] == "https://a.co" and "https://c.co" in urls[1:3]  # 交错


def test_deep_research_pins_previous_sources_and_carries_facts(cfg, monkeypatch):
    """抗波动：上轮 trusted 来源钉住重抓；上轮 high facts 与 salary_signals 并集保留。"""
    import json as _json
    ddir = cfg.workspace_dir / "14-dossiers"
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "Acme-AI.json").write_text(_json.dumps({
        "fetched_at": "2026-08-08", "mode": "deep",
        "facts": [{"claim": "给基金经理配 AI 专家", "category": "org",
                   "source": "[8] fnlondon.com", "confidence": "high"},
                  {"claim": "低置信旧闻", "category": "other",
                   "source": "[9] x", "confidence": "low"}],
        "salary_signals": ["Avg. Salary $125.2k"],
        "sources": [{"n": 1, "title": "FN London", "tier": "trusted",
                     "url": "https://fnlondon.example/acme"}]}, ensure_ascii=False),
        encoding="utf-8")

    monkeypatch.setattr("joblander.search.web_search", lambda c, q, max_results=4: [
        {"title": "About", "url": "https://acme.ai/about", "snippet": ""}])
    monkeypatch.setattr("joblander.researcher.fetch_url",
                        lambda u, timeout=20: ("FN pinned content. " * 40) if "fnlondon" in u
                        else ("Acme AI platform. " * 40))
    llm = MockLLM([
        json.dumps({"queries": ["Acme AI"]}),
        json.dumps({"thought": "覆盖", "coverage": {}, "queries": []}),
        json.dumps({"summary_md": ("**这家公司是谁** x [1]\n**为什么现在招这个岗** y [1]\n"
                                   "**工程与技术侧** z [2]\n**对你意味着什么** w。$125.2k [1]"),
                    "facts": [{"claim": "新事实", "category": "org",
                               "source": "[2] acme.ai", "confidence": "high"}],
                    "salary_signals": [], "risks": [], "gaps": []}),
    ])
    from joblander.researcher import diligence
    d = diligence(cfg, llm, "Acme AI")
    synth_prompt = llm.calls[-1]["prompt"]
    assert "上轮调研存档" in synth_prompt                    # 历史事实进综合语料
    assert "给基金经理配 AI 专家" in synth_prompt
    urls = [s["url"] for s in d["sources"]]
    assert "https://fnlondon.example/acme" in urls          # 钉住来源回归语料
    assert any("上轮钉住" in s["title"] for s in d["sources"])
    claims = {f["claim"]: f for f in d["facts"]}
    assert "新事实" in claims
    assert claims["给基金经理配 AI 专家"]["carried_from"] == "2026-08-08"   # high 结转
    assert "低置信旧闻" not in claims                        # low 不结转
    assert "Avg. Salary $125.2k" in d["salary_signals"]      # 信号并集


def test_format_renumbers_and_hides_bookkeeping():
    """展示层：跳号重排连续、正文引用重映射、无关材料记账不上屏。"""
    from joblander.researcher import format_deep_summary
    d = {"mode": "deep", "jd_used": False,
         "summary_md": "**这家公司是谁** A 事实 [7]。B 事实 [3][7]。C 事实 [10]。",
         "sources": [{"n": 3, "title": "S3（上轮钉住）", "url": "https://s3.co", "tier": "trusted"},
                     {"n": 7, "title": "S7", "url": "https://s7.co", "tier": "official"},
                     {"n": 10, "title": "S10", "url": "https://s10.co", "tier": "aggregator"},
                     {"n": 12, "title": "无关站", "url": "https://x.co", "tier": "aggregator"}],
         "gaps": ["薪酬 band 未知", "材料[12]与目标公司无关", "材料 [2] 与目标公司无关"]}
    md = format_deep_summary(d)
    assert "[1]" in md and "[2]" in md and "[3]" in md and "[7]" not in md and "[10]" not in md
    assert md.index("1. [S7](https://s7.co)") < md.index("2. [S3](https://s3.co)")  # 按正文出现序
    assert "3. [S10]" in md and "无关站" not in md
    assert "（上轮钉住）" not in md
    assert "薪酬 band 未知" in md and "与目标公司无关" not in md


def test_html_to_md_keeps_block_structure():
    """抓取转文本保住块结构：列表成 - 、标题成 ##、段落换行、实体解码——
    此前全部空白折叠成一整行，JD 快照没法读（2026-08-11 报障）。"""
    from joblander.researcher import _html_to_md
    html = ("<html><head><style>x{}</style><script>var a=1;</script></head><body>"
            "<h2>Responsibilities</h2><p>Build &amp; run the LLM platform.</p>"
            "<ul><li>Design  APIs</li><li>Own SLOs</li><li><img/></li></ul>"
            "<div>5+ yoe</div></body></html>")
    out = _html_to_md(html)
    assert "## Responsibilities" in out
    assert "Build & run the LLM platform." in out       # 实体解码
    assert "- Design APIs\n" in out and "- Own SLOs" in out
    assert "\n-\n" not in out and not out.endswith("-")   # 空 li 不留光杆弹点
    assert "var a=1" not in out and "\n\n\n" not in out
    assert out.splitlines()[-1].strip() == "5+ yoe"


def test_diligence_mcf_salary_page(cfg, monkeypatch):
    """MCF 结构化薪酬进尽调：该公司挂牌岗位成一页证据（别家的岗过滤掉），
    tier 标「MCF·官方挂牌」；MCF 不可用（autouse 缺省）不阻塞照常检索。"""
    monkeypatch.setattr("joblander.sourcing.mcf_search", lambda kw, limit=16, timeout=10: [
        {"title": "Senior Data Engineer", "postedCompany": {"name": "ACME AI PTE. LTD."},
         "salary": {"minimum": 9000, "maximum": 15000,
                    "type": {"salaryType": "Monthly"}},
         "metadata": {"newPostingDate": "2026-08-10"}},
        {"title": "Staff ML Engineer", "postedCompany": {"name": "Acme AI"},
         "salary": {}, "metadata": {}},
        {"title": "Chef", "postedCompany": {"name": "Other Kitchen"},   # 别家的岗
         "salary": {"minimum": 3000, "maximum": 4000,
                    "type": {"salaryType": "Monthly"}}, "metadata": {}},
    ])
    monkeypatch.setattr("joblander.search.web_search", lambda c, q, max_results=4: [
        {"title": "About", "url": "https://acme.ai/about", "snippet": ""}])
    monkeypatch.setattr("joblander.researcher.fetch_url",
                        lambda u, timeout=20: "Acme AI agent platform. " * 40)
    llm = MockLLM([
        json.dumps({"queries": ["Acme AI"]}),
        json.dumps({"thought": "薪酬已有 MCF 挂牌", "coverage": {"薪酬": "有"},
                    "queries": []}),
        json.dumps({"summary_md": "**这家公司是谁** x [1]。DE 挂牌 9000–15000 [2]。",
                    "facts": [], "salary_signals": ["9000–15000 SGD/Monthly"],
                    "risks": [], "gaps": []}),
    ])
    from joblander.researcher import diligence, format_deep_summary
    d = diligence(cfg, llm, "Acme AI", context="目标岗位：Data Engineer；阶段：Applied")
    react_prompt = llm.calls[1]["prompt"]
    assert "MCF·官方挂牌" in react_prompt                      # 证据页进了判读摘录
    assert "9000–15000 SGD/Monthly" in react_prompt
    assert "Other Kitchen" not in react_prompt                 # 别家的岗被过滤
    assert llm.calls[0]["system"] and "规划" in llm.calls[0]["system"]   # 盲扫照跑（不算喂料）
    mcf_src = next(s for s in d["sources"] if s["tier"] == "mcf")
    assert "mycareersfuture.gov.sg" in mcf_src["url"]
    assert "🏛️MCF挂牌" in format_deep_summary(d)               # 渲染摘要带 tier 标记
