"""LinkedIn 公开职位：解析（真实页面结构的精简样本）+ 与 MCF 同一条查重/评分/入池管线。"""

import json

from joblander import sourcing as S
from joblander.config import Config
from joblander.llm import MockLLM

CARD = """<li>
 <div class="base-card job-search-card" data-entity-urn="urn:li:jobPosting:4420482236">
  <a class="base-card__full-link absolute" href="https://sg.linkedin.com/jobs/view/software-developer-at-acme-4420482236?position=1&amp;pageNum=0">
  <h3 class="base-search-card__title">
        Software Developer
  </h3>
  <h4 class="base-search-card__subtitle">
    <a class="hidden-nested-link" href="x">  Acme &amp; Co  </a>
  </h4>
  <span class="job-search-card__location">  Singapore, Singapore  </span>
  <time class="job-search-card__listdate--new" datetime="2099-10-04">1 hour ago</time>
 </div></li>"""

DETAIL = """<div class="show-more-less-html__markup relative">We need <strong>5+ years</strong> Python.</div>
<h3 class="description__job-criteria-subheader">
 Seniority level
</h3>
<span class="description__job-criteria-text">
 Mid-Senior level
</span>"""


def test_parse_cards_and_detail():
    [c] = S.parse_linkedin_cards("<ul>" + CARD + "</ul>")
    assert c == {"id": "4420482236", "title": "Software Developer", "company": "Acme & Co",
                 "location": "Singapore, Singapore", "posted": "2099-10-04",
                 "url": "https://sg.linkedin.com/jobs/view/software-developer-at-acme-4420482236"}
    d = S.parse_linkedin_detail(DETAIL)
    assert d["description"] == "We need 5+ years Python."
    assert d["criteria"] == {"Seniority level": "Mid-Senior level"}
    lead = S.linkedin_to_lead(c, d)
    assert lead["jd_excerpt"].startswith("We need") and "Mid-Senior" in lead["highlight"]


def _cfg(tmp_path, linkedin=True):
    ws = tmp_path / "ws"
    (ws / "09-projections").mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text(json.dumps(
        {"rows": [{"Company": "Tracked Ltd", "Status": "Applied"}]}), encoding="utf-8")
    (ws / "02-targets").mkdir()
    (ws / "02-targets" / "sourcing-prefs.yaml").write_text(
        "keywords: [software engineer]\nlocations: [Singapore]\nexclude: [intern]\n", encoding="utf-8")
    return Config(raw={"workspace_dir": str(ws), "features": {"linkedin": linkedin}},
                  path=tmp_path / "c.yaml")


def test_source_linkedin_pipeline(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cards = [
        {"id": "1", "title": "Backend Engineer", "company": "NewCo", "location": "SG",
         "posted": "2099-01-01", "url": "u1"},
        {"id": "2", "title": "Backend Engineer", "company": "NewCo", "location": "SG",
         "posted": "2099-01-01", "url": "u2"},                       # 同轮重复挂牌
        {"id": "3", "title": "Software Intern", "company": "X", "location": "SG",
         "posted": "2099-01-01", "url": "u3"},                       # 排除词
        {"id": "4", "title": "SWE", "company": "Tracked Ltd", "location": "SG",
         "posted": "2099-01-01", "url": "u4"},                       # 已在库
    ]
    calls = []
    monkeypatch.setattr(S, "linkedin_search", lambda kw, loc, hours=48, start=0:
                        calls.append((kw, loc, hours)) or cards)
    monkeypatch.setattr(S, "_li_get", lambda url, timeout=20: DETAIL)
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(S, "assess_fit", lambda cfg, llm, lead, jd_text="": {"fit": 4, "jd": jd_text})
    outs = S.source_linkedin(cfg, MockLLM([]))
    assert calls == [("software engineer", "Singapore", 48)]
    assert len(outs) == 1
    prop = json.loads(outs[0].read_text(encoding="utf-8"))
    assert prop["source_hint"] == "linkedin" and prop["lead"]["company"] == "NewCo"
    assert prop["fit"]["jd"].startswith("We need")                  # 详情喂给了初筛
    assert S.source_linkedin(cfg, MockLLM([])) == []                 # 幂等：见过的不再提


def test_linkedin_off_or_blocked_never_raises(tmp_path, monkeypatch):
    assert S.source_linkedin(_cfg(tmp_path / "a", linkedin=False), MockLLM([])) == []
    cfg = _cfg(tmp_path / "b")
    def blocked(*a, **k):
        raise OSError("429 Too Many Requests")
    monkeypatch.setattr(S, "linkedin_search", blocked)
    monkeypatch.setattr(S, "source_mcf", lambda cfg, llm, days=2: [])
    assert S.source_all(cfg, MockLLM([])) == {"mcf": 0, "linkedin": 0}
