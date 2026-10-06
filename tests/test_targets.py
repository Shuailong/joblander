"""目标公司定向搜索：认招聘系统、统一岗位格式、地点筛 → 标题挑选 → 评分入池、跨轮去重。全合成，不触网。"""

import json
import urllib.error

import pytest

from joblander import sourcing, targets
from joblander.config import Config


@pytest.fixture
def cfg(tmp_path):
    proj = tmp_path / "09-projections"
    proj.mkdir(parents=True)
    (proj / "tracker.json").write_text(json.dumps({"rows": [
        {"Company": "Acme AI", "notion_page_id": "aaa111", "Status": "Applied"}]}))
    c = Config(raw={"workspace_dir": str(tmp_path), "features": {"linkedin": False}},
               path=tmp_path / "c.yaml")
    sourcing.save_prefs(c, {"intent": "ML systems", "keywords": ["AI Engineer"],
                            "locations": ["Singapore"], "exclude": ["intern"]})
    return c


GH = {"jobs": [
    {"id": 1, "title": "ML Engineer", "location": {"name": "Singapore"},
     "absolute_url": "https://stripe.example/jobs/1", "first_published": "2099-01-02T00:00:00Z",
     "company_name": "Stripe", "content": "&lt;p&gt;Build &lt;b&gt;ML&lt;/b&gt; &amp;amp; infra&lt;/p&gt;"},
    {"id": 2, "title": "Account Executive", "location": {"name": "Singapore"},
     "absolute_url": "https://stripe.example/jobs/2", "company_name": "Stripe", "content": ""},
    {"id": 3, "title": "ML Engineer", "location": {"name": "Seattle"},
     "absolute_url": "https://stripe.example/jobs/3", "company_name": "Stripe", "content": ""},
    {"id": 4, "title": "Data Intern", "location": {"name": "Singapore"},
     "absolute_url": "https://stripe.example/jobs/4", "company_name": "Stripe", "content": ""},
]}
LEVER = [{"id": "lv1", "text": "AI Platform Engineer", "hostedUrl": "https://jobs.lever.co/kite/lv1",
          "createdAt": 4070908800000, "categories": {"location": "Singapore"},
          "descriptionPlain": "Own the LLM platform.", "lists": [{"text": "Req", "content": "<li>5y Python</li>"}]}]
ASHBY = {"jobs": [{"id": "a1", "title": "Research Engineer", "location": "Remote",
                   "secondaryLocations": [{"location": "Singapore"}], "jobUrl": "https://jobs.ashbyhq.com/zed/a1",
                   "publishedAt": "2099-01-03T00:00:00Z", "descriptionPlain": "Evals.", "isListed": True},
                  {"id": "a2", "title": "Hidden", "isListed": False}]}


def fake_net(monkeypatch, boards, calls=None):
    """boards: {api url 片段: payload}；没命中的 → 404。"""
    def get(url, timeout=25):
        if calls is not None:
            calls.append(url)
        for frag, payload in boards.items():
            if frag in url:
                return payload
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)
    monkeypatch.setattr(targets, "_get_json", get)


class LLM:
    def __init__(self, picks=(0,)):
        self.picks, self.screens, self.fits, self.listings = list(picks), 0, 0, []

    def generate(self, prompt, system=None, json_mode=False):
        if system.startswith("你是求职侦察的初筛员"):
            self.screens += 1
            self.listings.append(prompt.split("在招岗位：\n")[1])
            return json.dumps({"picks": self.picks})
        self.fits += 1
        return json.dumps({"fit": 4, "why": "对口", "flags": []})


def test_parse_board_url_and_slugs():
    assert targets.parse_board_url("https://boards.greenhouse.io/Stripe/jobs/123") == ("greenhouse", "stripe")
    assert targets.parse_board_url("job-boards.greenhouse.io/figma") == ("greenhouse", "figma")
    assert targets.parse_board_url("https://jobs.lever.co/kite?team=x") == ("lever", "kite")
    assert targets.parse_board_url("https://jobs.ashbyhq.com/zed/abc") == ("ashby", "zed")
    assert targets.parse_board_url("Stripe") is None
    assert targets.slug_candidates("Scale AI, Inc.") == ["scaleai", "scale-ai"]


def test_fetch_board_normalizes_three_systems(monkeypatch):
    fake_net(monkeypatch, {"/boards/stripe/": GH, "/postings/kite": LEVER, "/job-board/zed": ASHBY})
    gh = targets.fetch_board("greenhouse", "stripe")
    assert gh[0]["jd"] == "Build ML & infra"                   # 双重转义的 HTML 剥干净
    assert gh[0]["posted"] == "2099-01-02" and gh[0]["company"] == "Stripe"
    lv = targets.fetch_board("lever", "kite")[0]
    assert lv["posted"] == "2099-01-01" and "5y Python" in lv["jd"]
    ash = targets.fetch_board("ashby", "zed")
    assert len(ash) == 1 and ash[0]["location"] == "Remote / Singapore"


def test_source_targets_screens_then_scores_and_only_new_next_time(cfg, monkeypatch):
    calls = []
    fake_net(monkeypatch, {"/boards/stripe/": GH, "/postings/kite": LEVER}, calls)
    sourcing.save_prefs(cfg, {"targets": ["Stripe", "https://jobs.lever.co/kite"]})
    llm = LLM(picks=[0, 99, 0])                               # 越界、重复的编号被丢掉
    outs = targets.source_targets(cfg, llm)
    assert len(outs) == 2 and llm.screens == 2 and llm.fits == 2
    # 西雅图的被地点筛掉、intern 被排除词挡掉——都没进标题清单
    assert llm.listings[0] == "0|ML Engineer|Singapore\n1|Account Executive|Singapore"
    prop = json.loads(outs[0].read_text())
    assert prop["lead"]["target"] and prop["lead"]["company"] == "Stripe"
    assert prop["lead"]["jd_excerpt"] == "Build ML & infra" and prop["fit"]["fit"] == 4
    st = targets.load_status(cfg)
    assert st["Stripe"] | {"ts": ""} == {"ts": "", "name": "Stripe", "ats": "greenhouse",
                                          "board_url": "https://job-boards.greenhouse.io/stripe",
                                          "total": 4, "local": 3, "new": 2, "picked": 1, "proposed": 1,
                                          "proposed_total": 1}
    assert st["https://jobs.lever.co/kite"]["name"] == "Kite"
    # 认出的 slug 缓存：第二轮直接拉，不再挨个试
    calls.clear()
    llm2 = LLM()
    assert targets.source_targets(cfg, llm2) == []
    assert llm2.screens == 0 and llm2.fits == 0               # 没有新岗 → 一次 LLM 都不花
    assert sum("greenhouse" in u for u in calls) == 1


def test_already_tracked_company_costs_nothing(cfg, monkeypatch):
    fake_net(monkeypatch, {"/boards/acmeai/": {"jobs": [dict(GH["jobs"][0], company_name="Acme AI")]}})
    sourcing.save_prefs(cfg, {"targets": ["Acme AI"]})
    llm = LLM()
    assert targets.source_targets(cfg, llm) == [] and llm.screens == 0
    assert targets.load_status(cfg)["Acme AI"]["tracked"] == "Acme AI"


def test_guessed_slug_of_another_company_is_rejected_then_falls_back(cfg, monkeypatch):
    fake_net(monkeypatch, {"/boards/kite/": {"jobs": [dict(GH["jobs"][0], company_name="Kite Realty")]}})
    monkeypatch.setattr(sourcing, "mcf_search", lambda kw, limit=50: [
        {"uuid": "u" * 32, "title": "AI Engineer", "postedCompany": {"name": "KITE PTE. LTD."},
         "metadata": {"newPostingDate": "2099-01-01"}},
        {"uuid": "v" * 32, "title": "AI Engineer", "postedCompany": {"name": "Other Co"}}])
    monkeypatch.setattr(sourcing, "mcf_job_detail", lambda uuid: {"description": "<p>LLM evals</p>"})
    sourcing.save_prefs(cfg, {"targets": ["Kite"]})
    llm = LLM()
    outs = targets.source_targets(cfg, llm)
    assert len(outs) == 1 and llm.listings == ["0|AI Engineer|Singapore"]   # 公司名对不上的被滤掉
    prop = json.loads(outs[0].read_text())
    assert prop["lead"]["target"] and "LLM evals" in prop["lead"]["jd_excerpt"]
    assert prop["lead"]["company"] == "Kite"                  # 不是 MCF 上的法人全名
    st = targets.load_status(cfg)["Kite"]
    assert st["ats"] == "" and st["total"] == 1


def test_screen_failure_leaves_titles_for_next_run(cfg, monkeypatch):
    fake_net(monkeypatch, {"/boards/stripe/": GH})
    sourcing.save_prefs(cfg, {"targets": ["Stripe"]})

    class Broken(LLM):
        def generate(self, *a, **k):
            raise RuntimeError("quota")
    assert targets.source_targets(cfg, Broken()) == []
    assert "quota" in targets.load_status(cfg)["Stripe"]["error"]
    llm = LLM()
    assert len(targets.source_targets(cfg, llm)) == 1 and llm.screens == 1


def test_source_all_includes_targets(cfg, monkeypatch):
    monkeypatch.setattr(sourcing, "source_mcf", lambda *a, **k: [])
    monkeypatch.setattr(sourcing, "source_linkedin", lambda *a, **k: [])
    monkeypatch.setattr(targets, "source_targets", lambda *a, **k: ["x"])
    assert sourcing.source_all(cfg, LLM()) == {"mcf": 0, "linkedin": 0, "targets": 1}


def test_name_check():
    assert targets._name_ok("Grab", "Grab Holdings")
    assert targets._name_ok("Scale AI", "Scale AI")
    assert not targets._name_ok("Kite", "Kite Realty")


def test_web_save_targets_and_render(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    ws = tmp_path / "ws"
    (ws / "09-projections").mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text('{"rows": []}', encoding="utf-8")
    c = Config(raw={"workspace_dir": str(ws), "sentinel": {"rules": []}}, path=tmp_path / "c.yaml")
    monkeypatch.setattr("joblander.web.app.load_config", lambda: c)
    from joblander import wizard
    wizard.skip(c)
    from joblander.web.app import create_app
    client = TestClient(create_app(with_daemon=False), base_url="http://127.0.0.1")
    assert client.post("/api/sourcing/scan").status_code == 400       # 关键词、目标公司都没填
    r = client.post("/api/sourcing/prefs", data={"targets": "Stripe\n\nhttps://jobs.lever.co/kite，Stripe"})
    assert r.json()["ok"]
    assert sourcing.load_prefs(c)["targets"] == ["Stripe", "https://jobs.lever.co/kite"]
    targets._save_json(targets.status_path(c), {"Stripe": {
        "ts": "2099-01-01T02:30:00", "name": "Stripe", "ats": "greenhouse",
        "board_url": "https://job-boards.greenhouse.io/stripe",
        "total": 721, "local": 12, "new": 12, "picked": 3, "proposed": 3}})
    html = client.get("/sourcing").text
    assert "/api/sourcing/targets/scan" not in html            # 没有单独的入口：并进搜索偏好 + 立即搜
    assert 'title="在招 721 · 你的地点 12 · 本轮新出现 12 · 累计挑出 3">Stripe · 12</a>' in html
    assert 'title="还没搜过——点「立即搜」">https://jobs.lever.co/kite</span>' in html
    assert "Stripe\nhttps://jobs.lever.co/kite</textarea>" in html
    assert "先告诉系统你在找什么" not in html                  # 只填目标公司也算配置过
    en = client.get("/sourcing", headers={"Accept-Language": "en-US,en"}).text
    assert "721 open · 12 in your locations" in en
    monkeypatch.setattr("joblander.sourcing.source_all", lambda *a, **k: {})
    assert client.post("/api/sourcing/scan").json()["ok"]      # 只有目标公司也能「立即搜」


def test_status_keeps_running_total(cfg, monkeypatch):
    fake_net(monkeypatch, {"/boards/stripe/": GH})
    sourcing.save_prefs(cfg, {"targets": ["Stripe"]})
    targets.source_targets(cfg, LLM())
    targets.source_targets(cfg, LLM())                          # 第二轮没新岗
    st = targets.load_status(cfg)["Stripe"]
    assert st["proposed"] == 0 and st["proposed_total"] == 1


def test_sourcing_page_target_section_first_with_clear_empty_states(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    ws = tmp_path / "ws"
    (ws / "09-projections").mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text('{"rows": []}', encoding="utf-8")
    c = Config(raw={"workspace_dir": str(ws), "sentinel": {"rules": []}}, path=tmp_path / "c.yaml")
    monkeypatch.setattr("joblander.web.app.load_config", lambda: c)
    from joblander import wizard
    wizard.skip(c)
    sourcing.save_prefs(c, {"keywords": ["AI Engineer"], "locations": ["Singapore"],
                            "targets": ["Stripe", "Anthropic", "Acme", "Faraway", "Newco"]})
    targets._save_json(targets.status_path(c), {
        "Stripe": {"ts": "2099-01-01T02:30:00", "name": "Stripe", "ats": "greenhouse",
                   "board_url": "https://job-boards.greenhouse.io/stripe", "total": 720, "local": 52, "proposed_total": 1},
        "Anthropic": {"ts": "2099-01-01T02:30:00", "name": "Anthropic", "ats": "greenhouse", "board_url": "x",
                      "total": 642, "local": 11, "proposed_total": 0},
        "Acme": {"ts": "2099-01-01T02:30:00", "name": "Acme", "tracked": "Acme Corp"},
        "Faraway": {"ts": "2099-01-01T02:30:00", "name": "Faraway", "ats": "lever", "board_url": "y", "total": 9, "local": 0}})
    intake = ws / "12-intake"
    intake.mkdir()
    for fn, lead in (("a-stripe.json", {"company": "Stripe", "position": "ML Engineer", "target": True}),
                     ("b-other.json", {"company": "Other Co", "position": "AI Engineer"})):
        (intake / fn).write_text(json.dumps({"kind": "lead.intake", "lead": lead, "dedupe": {"verdict": "new"},
                                             "source_hint": "mcf", "fit": {"fit": 4, "why": "对口"}, "approved": None}))
    from joblander.web.app import create_app
    html = TestClient(create_app(with_daemon=False), base_url="http://127.0.0.1").get("/sourcing").text
    sec = html.split('id="targets"')[1].split("其他新机会")[0]
    assert "5 家 · 1 个岗位待你决定" in sec
    assert sec.index("ML Engineer") < sec.index("Anthropic")            # Stripe 的岗位在 Stripe 卡里
    assert "Other Co" not in sec and "Other Co" in html.split("其他新机会")[1]
    assert "暂时没有适合你的岗位" in sec and "你的地点在招 11 个都看过了" in sec
    assert "已在你的战线里" in sec and "Acme Corp" in sec
    assert "你的地点没有在招岗位" in sec and "它在招 9 个" in sec
    assert "还没搜过" in sec                                              # Newco
