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


# ---------- 隐私 v2 的行为数据（多租户形态，网关说这个账户可以记时才记） ----------

def _behavior_env(monkeypatch):
    monkeypatch.setattr(telemetry, "_events_started", True)        # 不起后台发送线程
    monkeypatch.setattr(telemetry, "_events", [])
    monkeypatch.setenv("JOBLANDER_LOG_SALT", "salt")
    monkeypatch.setenv("JOBLANDER_MODE", "multi")
    monkeypatch.setenv("JOBLANDER_EVENTS_TOPIC", "projects/p/topics/events")


def test_behavior_only_with_gateway_flag_topic_and_multi(monkeypatch):
    import contextvars

    from joblander.obs import user_key
    from joblander.tenancy import Tenant, use_tenant
    _behavior_env(monkeypatch)

    def run(on, method="GET", route="/company/{page_id}"):
        def inner():
            telemetry.set_analytics(on)
            with use_tenant(Tenant("tenant-a", None)):
                return telemetry.behavior(method, route, 404, 12.345, now=7.0)
        return contextvars.copy_context().run(inner)       # 开关是上下文变量，别漏到别的测试
    assert not run(False)                                   # 网关说不能记
    assert run(True)
    assert not run(True, route="/api/tasks") and not run(True, route="/static/app.css")
    assert telemetry._events == [{"v": 1, "type": "request", "user_key": user_key("tenant-a"), "at": 7.0,
                                  "method": "GET", "route": "/company/{page_id}", "status": 404, "ms": 12.3}]
    monkeypatch.delenv("JOBLANDER_EVENTS_TOPIC")
    assert not run(True)                                    # 没配主题（staging 之外、或本机）
    monkeypatch.setenv("JOBLANDER_EVENTS_TOPIC", "projects/p/topics/events")
    monkeypatch.delenv("JOBLANDER_MODE")
    assert not run(True)                                    # Fly / 本机形态从不记


def test_flush_behavior_publishes_and_drops_on_error(monkeypatch):
    _behavior_env(monkeypatch)
    telemetry._events.extend({"n": i} for i in range(501))
    sent = []
    monkeypatch.setattr("joblander.gcp.pubsub_publish", lambda topic, batch: sent.append((topic, len(batch))))
    assert telemetry.flush_behavior("projects/p/topics/events") == 500
    assert telemetry.flush_behavior("projects/p/topics/events") == 1
    assert sent == [("projects/p/topics/events", 500), ("projects/p/topics/events", 1)]

    def boom(topic, batch):
        raise OSError("pubsub down")
    telemetry._events.append({"n": 0})
    monkeypatch.setattr("joblander.gcp.pubsub_publish", boom)
    assert telemetry.flush_behavior("projects/p/topics/events") == 0 and telemetry._events == []
