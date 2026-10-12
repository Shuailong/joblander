"""云端版的使用记录：只记「方法 + 路由模板」，不记具体路径与内容；本机版不记。"""

from joblander import telemetry


def _reset():
    telemetry.drain()


def test_records_route_templates_not_paths(tmp_path, monkeypatch):
    from tests.test_cloud_ui import _client
    monkeypatch.setenv("OPENAI_BASE_URL", "http://meter/v1")
    _reset()
    c = _client(tmp_path, monkeypatch, cloud=True)
    c.get("/sourcing")
    c.get("/company/acme-secret-co")                 # 404 也好 200 也好，都不能出现具体值
    c.get("/api/tasks")                              # 轮询不算
    names = [n for n, _ in telemetry.drain()]
    assert "GET /sourcing" in names and "GET /api/tasks" not in names
    assert not any("acme" in n for n in names)


def test_local_records_nothing(tmp_path, monkeypatch):
    from tests.test_cloud_ui import _client
    _reset()
    c = _client(tmp_path, monkeypatch, cloud=False)
    c.get("/sourcing")
    assert telemetry.drain() == []


def test_flush_posts_batch_to_meter(monkeypatch):
    import json
    monkeypatch.setenv("JOBLANDER_GATEWAY_TOKEN", "t")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://meter/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sub-key")
    _reset()
    telemetry.record("POST", "/api/sourcing/prefs", now=5.0)
    telemetry.record("GET", "/static/app.css")
    sent = {}

    class R:
        def read(self):
            return b"{}"

    def fake_open(req, timeout):
        sent["url"], sent["auth"], sent["body"] = req.full_url, req.headers["Authorization"], json.loads(req.data)
        return R()
    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    assert telemetry.flush() == 1
    assert sent == {"url": "http://meter/v1/events", "auth": "Bearer sub-key",
                    "body": {"events": [{"name": "POST /api/sourcing/prefs", "at": 5.0}]}}
