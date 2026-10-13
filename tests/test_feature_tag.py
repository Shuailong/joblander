"""云端版的功能标签：AI / 搜索调用带上「当前在做哪件事」，网关按它记每个功能的花费。"""

import time

from joblander.llm import FEATURE


def test_metered_calls_carry_feature_header_direct_calls_dont(monkeypatch):
    from joblander import llm as L
    seen = []
    monkeypatch.setattr(L, "_http_sse_text", lambda url, body, headers, timeout=300: seen.append(headers) or "ok")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    tok = FEATURE.set("POST /api/resume/react")
    try:
        L.OpenAIChat("gpt-4o", base_url="http://meter/v1").generate("hi")
        L.OpenAIChat("gpt-4o").generate("hi")                    # 本机直连 OpenAI：不带
    finally:
        FEATURE.reset(tok)
    L.OpenAIChat("gpt-4o", base_url="http://meter/v1").generate("hi")   # 没有当前功能：不带
    assert seen[0]["X-Joblander-Feature"] == "POST /api/resume/react"
    assert "X-Joblander-Feature" not in seen[1] and "X-Joblander-Feature" not in seen[2]


def test_request_route_and_background_task_inherit_feature(tmp_path, monkeypatch):
    from tests.test_cloud_ui import _client
    monkeypatch.setenv("OPENAI_BASE_URL", "http://meter/v1")
    monkeypatch.delenv("JOBLANDER_TASKS_SYNC", raising=False)
    c = _client(tmp_path, monkeypatch, cloud=True)
    app = c.app
    from joblander.web.app import TASKS, start_task

    @app.get("/_t/now/{x}")
    def now(x: str):
        return {"f": FEATURE.get()}

    @app.post("/_t/task/{x}")
    def task(x: str):
        return {"tid": start_task("t", "t", lambda: FEATURE.get())}
    assert c.get("/_t/now/acme-secret").json() == {"f": "GET /_t/now/{x}"}       # 模板，不含具体值
    tid = c.post("/_t/task/acme").json()["tid"]
    for _ in range(100):
        if TASKS[tid]["status"] != "running":
            break
        time.sleep(0.02)
    assert TASKS[tid]["result"] == "POST /_t/task/{x}"
    assert FEATURE.get() == ""


def test_daemon_jobs_are_tagged(tmp_path):
    from joblander.daemon import Daemon
    seen = []
    d = Daemon.__new__(Daemon)
    d.jobs = [("nightly_sourcing", lambda: seen.append(FEATURE.get()))]
    d.running = None
    d._save_state = lambda: None
    d.tick()
    assert seen == ["job:nightly_sourcing"] and FEATURE.get() == ""


def test_search_threads_keep_feature(monkeypatch):
    from joblander import search as S
    seen = []
    monkeypatch.setattr(S, "_providers", lambda cfg: [{"provider": "gateway", "url": "http://meter/v1/search"}])
    monkeypatch.setattr(S, "_one_provider", lambda pv, q, n: seen.append(FEATURE.get()) or [])
    tok = FEATURE.set("POST /api/company/research")
    try:
        S.web_search(None, "q")
    except Exception:                                          # noqa: BLE001  空结果怎么报错不关心
        pass
    finally:
        FEATURE.reset(tok)
    assert seen == ["POST /api/company/research"]
