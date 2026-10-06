"""云端版的账户入口：额度、隐私、后台、退出收进侧栏账户菜单与设置页「账户」，不再常驻侧栏。"""

from fastapi.testclient import TestClient

from joblander.config import Config


def _client(tmp_path, monkeypatch, cloud: bool):
    ws = tmp_path / "ws"
    (ws / "09-projections").mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text('{"rows": []}', encoding="utf-8")
    cfg = Config(raw={"workspace_dir": str(ws), "sentinel": {"rules": []}}, path=tmp_path / "c.yaml")
    monkeypatch.setattr("joblander.web.app.load_config", lambda: cfg)
    if cloud:
        monkeypatch.setenv("JOBLANDER_GATEWAY_TOKEN", "t")
    else:
        monkeypatch.delenv("JOBLANDER_GATEWAY_TOKEN", raising=False)
    from joblander import wizard
    wizard.skip(cfg)
    from joblander.web.app import create_app
    return TestClient(create_app(with_daemon=False), base_url="http://127.0.0.1",
                      headers={"x-joblander-gateway": "t"} if cloud else {})


def test_cloud_sidebar_has_account_menu_not_balance(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch, cloud=True).get("/sourcing").text
    assert 'id="acct-menu"' in html and "/_gw/me" in html
    menu = html.split('id="acct-menu"')[1].split("<main")[0]
    for link in ("/settings#account", "/_gw/privacy", "/_gw/admin", "/auth/logout"):
        assert link in menu, link
    assert 'id="quota"' not in html and "/_gw/balance" not in html     # 额度不再常驻侧栏
    assert 'id="acct-admin" hidden' in html                            # 后台入口默认藏，/_gw/me 说是管理员才露


def test_cloud_settings_has_account_section(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch, cloud=True).get("/settings").text
    acct = html.split('id="account"')[1].split('id="data"')[0]
    assert "/auth/logout" in acct and "/_gw/account" in acct and 'id="me-admin" hidden' in acct


def test_local_has_no_account_ui(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, cloud=False)
    for path in ("/sourcing", "/settings"):
        html = c.get(path).text
        assert "acct-menu" not in html and "/_gw/" not in html and 'id="account"' not in html
