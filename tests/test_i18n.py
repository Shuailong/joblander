"""英文界面：已翻译的页面每个 _() 都有英文，英文渲染后可见文字里不残留中文。"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from joblander.config import Config
from joblander.web.i18n import jsq, pick_lang
from joblander.web.i18n_en import EN

TPL = Path(__file__).resolve().parents[1] / "joblander" / "web" / "templates"
TRANSLATED = ["base.html", "settings.html", "sourcing.html", "dashboard.html"]
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
