"""英文界面：已翻译的页面每个 _() 都有英文，英文渲染后可见文字里不残留中文。"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from joblander.config import Config
from joblander.web.i18n import jsq, pick_lang
from joblander.web.i18n_en import EN

TPL = Path(__file__).resolve().parents[1] / "joblander" / "web" / "templates"
TRANSLATED = sorted(p.name for p in TPL.glob("*.html"))
CJK = re.compile(r"[一-鿿]")


@pytest.mark.parametrize("name", TRANSLATED)
def test_every_marked_string_has_english(name):
    keys = re.findall(r"_\('([^']*)'", (TPL / name).read_text(encoding="utf-8"))
    missing = [k for k in keys if CJK.search(k) and k not in EN]
    assert not missing, missing


def test_pick_lang_and_jsq():
    assert pick_lang("zh", "en-US,en") == "zh"            # 设置里选过的优先
    assert pick_lang(None, "en-GB,en;q=0.9") == "en"
    assert pick_lang(None, "zh-CN,zh;q=0.9,en;q=0.8") == "zh"
    assert pick_lang(None, None) == "zh"
    assert str(jsq("it's \"x\" <b>")) == "'it\\x27s \\x22x\\x22 \\x3cb\\x3e'"


@pytest.fixture
def client(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / "09-projections").mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text('{"rows": []}', encoding="utf-8")
    cfg = Config(raw={"workspace_dir": str(ws), "sentinel": {"rules": []}}, path=tmp_path / "c.yaml")
    monkeypatch.setattr("joblander.web.app.load_config", lambda: cfg)
    from joblander import wizard
    wizard.skip(cfg)
    from joblander.web.app import create_app
    return TestClient(create_app(with_daemon=False), base_url="http://127.0.0.1"), cfg


def _visible(html: str) -> str:
    html = re.sub(r"<script.*?</script>|<!--.*?-->|<style.*?</style>", "", html, flags=re.S)
    html = html.replace("<option value=\"zh\"", "").replace(">中文<", "><")   # 语言选择器本身
    return re.sub(r"<[^>]+>", " ", html)


@pytest.mark.parametrize("path", ["/settings", "/sourcing", "/"])
def test_english_pages_have_no_chinese(client, path):
    c, _ = client
    html = c.get(path, headers={"Accept-Language": "en-US,en"}).text
    assert '<html lang="en">' in html
    left = CJK.findall(_visible(html))
    assert not left, re.findall(r".{0,20}[一-鿿]+.{0,20}", _visible(html))[:10]


def test_language_setting_overrides_browser(client):
    c, cfg = client
    assert c.post("/api/settings/lang", data={"lang": "en"}).status_code == 200
    assert '<html lang="en">' in c.get("/settings", headers={"Accept-Language": "zh-CN"}).text
    c.post("/api/settings/lang", data={"lang": "zh"})
    assert '<html lang="zh">' in c.get("/settings", headers={"Accept-Language": "en"}).text


def test_english_output_wraps_every_agent(tmp_path, monkeypatch):
    """英文界面：所有经 from_config 拿到的 LLM 都带上输出语言指令；中文界面原样。"""
    from joblander import llm as L
    seen = {}
    monkeypatch.setattr(L, "_from_config", lambda cfg, tier="pro": type("C", (), {
        "generate": lambda self, prompt, system=None, json_mode=False, effort=None:
            seen.update(system=system, prompt=prompt) or "ok"})())
    L.from_config(Config(raw={"ui_lang": "en"}, path=None)).generate("p", system="你是评估官")
    assert seen["system"].startswith("你是评估官") and "OUTPUT LANGUAGE" in seen["system"]
    assert "不符|存疑" in seen["system"]                  # 封闭取值点名不许翻
    assert "中介代招" in seen["system"]                   # 中文示例点名要改写成英文（实测曾被照抄）
    assert seen["prompt"].startswith("p") and "Answer in English" in seen["prompt"]
    L.from_config(Config(raw={}, path=None)).generate("p", system="你是评估官")
    assert seen["system"] == "你是评估官" and seen["prompt"] == "p"


def test_first_page_view_persists_language(client):
    c, cfg = client
    assert not cfg.raw.get("ui_lang")
    c.get("/settings", headers={"Accept-Language": "en-US", "Accept": "text/html"})
    assert cfg.raw["ui_lang"] == "en"                     # 后台任务 / AI 输出从此认它
    c.get("/settings", headers={"Accept-Language": "zh-CN", "Accept": "text/html"})
    assert cfg.raw["ui_lang"] == "en"                     # 之后只有设置里能改


def test_english_arsenal_scaffold_stays_internal():
    from joblander import wizard
    md = wizard.render_bank([{"title": "Acme", "items": [{"headline": "Did X", "detail": ""}]}], lang="en")
    assert md.startswith("# Achievement Arsenal") and "### A1. Did X" in md
    from joblander.arsenal import INTERNAL_PAT
    rules_title = [l for l in md.splitlines() if l.startswith("## ") and "⚠️" in l][0]
    assert INTERNAL_PAT.search(rules_title)


def test_lead_text_follows_language():
    from joblander import sourcing as S
    card = {"id": "1", "title": "PM", "company": "A", "location": "SG", "posted": "2026-10-01", "url": "u"}
    assert S.linkedin_to_lead(card, lang="en")["highlight"] == "LinkedIn listing 2026-10-01"
    assert S.linkedin_to_lead(card)["highlight"] == "LinkedIn 挂牌 2026-10-01"


def test_reset_zone_only_in_cloud(client, monkeypatch):
    c, _ = client
    assert "/_gw/reset" not in c.get("/settings").text          # 本地版没有网关，不给这个按钮
    monkeypatch.setenv("JOBLANDER_GATEWAY_TOKEN", "t")
    from joblander.web.app import create_app
    from fastapi.testclient import TestClient
    c2 = TestClient(create_app(with_daemon=False), base_url="http://127.0.0.1",
                    headers={"X-Joblander-Gateway": "t"})
    html = c2.get("/settings", headers={"Accept-Language": "en"}).text
    assert "/_gw/reset" in html and "Danger zone" in html


def test_gateway_set_lang_overrides_saved_language(client):
    c, cfg = client
    from joblander.config import update_config
    update_config(cfg, {"ui_lang": "zh"})
    html = c.get("/settings", headers={"X-Joblander-Set-Lang": "en"}).text
    assert cfg.raw["ui_lang"] == "en" and '<html lang="en">' in html


def test_research_report_english_skeleton():
    from joblander.researcher import format_deep_summary
    d = {"summary_md": "Strong fintech team [1].", "card": ["Raised Series C [1]"],
         "sources": [{"n": 1, "url": "https://x.example", "title": "OKX hiring（搜索摘要）", "tier": "aggregator"}],
         "gaps": ["salary band"], "trail": [{"round": 1, "coverage": {"动因": "缺", "薪酬": "死角", "面试": "有"},
                                             "queries": ["a"], "gained": 2}]}
    md = format_deep_summary(d, lang="en")
    assert not re.search(r"[一-鿿]", md), md
    assert "missing why hiring" in md and "blind spots pay" in md and "(search snippet)" in md
    zh = format_deep_summary(d)
    assert "缺 动因" in zh and "（搜索摘要）" in zh


def test_feedback_entry_cloud_dialog_local_github(client, monkeypatch):
    c, _ = client
    html = c.get("/settings").text
    assert "github.com/Shuailong/joblander/issues" in html and "/_gw/feedback" not in html
    monkeypatch.setenv("JOBLANDER_GATEWAY_TOKEN", "t")
    from joblander.web.app import create_app
    c2 = TestClient(create_app(with_daemon=False), base_url="http://127.0.0.1",
                    headers={"X-Joblander-Gateway": "t"})
    html = c2.get("/settings", headers={"Accept-Language": "en"}).text
    assert "/_gw/feedback" in html and "Feedback" in html
