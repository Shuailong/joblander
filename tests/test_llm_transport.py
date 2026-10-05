import json
from joblander.llm import _http_sse_text, _with_retry, LLMError
import pytest

def test_sse_parse(monkeypatch):
    lines = [b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n',
             b'\n',
             b'data: {"choices":[{"delta":{"content":"lo"}}]}\n',
             b'data: [DONE]\n']
    class R:
        def __enter__(self): return iter(lines)
        def __exit__(self, *a): pass
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=0: R())
    assert _http_sse_text("http://x", {}, {}) == "Hello"

def test_retry_transient(monkeypatch):
    calls = []
    def fn():
        calls.append(1)
        if len(calls) < 3: raise ConnectionResetError(54, "reset")
        return "ok"
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert _with_retry(fn) == "ok" and len(calls) == 3

def test_retry_gives_up_and_no_retry_on_llmerror(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(LLMError, match="重试 3 次"):
        _with_retry(lambda: (_ for _ in ()).throw(ConnectionResetError(54, "r")))
    calls = []
    def bad():
        calls.append(1); raise LLMError("400: bad request")
    with pytest.raises(LLMError, match="400"):
        _with_retry(bad)
    assert len(calls) == 1


def test_openai_reasoning_models_omit_temperature(monkeypatch):
    """gpt-5/o 系 reasoning 模型只接受默认温度，body 不得带 temperature；-chat 变体不受限。"""
    from joblander import llm as L

    seen: dict = {}

    def fake_sse(url, body, headers, timeout=300):
        seen.clear(); seen.update(body); seen["_timeout"] = timeout; return "ok"

    monkeypatch.setattr(L, "_http_sse_text", fake_sse)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    L.OpenAIChat("gpt-5.6-sol").generate("hi")
    assert "temperature" not in seen
    assert seen["stream_options"] == {"include_usage": True}
    L.OpenAIChat("gpt-4o").generate("hi")
    assert seen["temperature"] == 0.2
    L.OpenAIChat("gpt-5.1-chat-latest").generate("hi")
    assert seen["temperature"] == 0.2


def test_openai_reasoning_effort_passthrough(monkeypatch):
    """effort 只对 reasoning 系生效（非 reasoning 传参会 400）；high 档放宽静默期超时。"""
    from joblander import llm as L

    seen: dict = {}

    def fake_sse(url, body, headers, timeout=300):
        seen.clear(); seen.update(body); seen["_timeout"] = timeout; return "ok"

    monkeypatch.setattr(L, "_http_sse_text", fake_sse)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    L.OpenAIChat("gpt-5.6-sol").generate("hi", effort="high")
    assert seen["reasoning_effort"] == "high" and seen["_timeout"] == 600
    L.OpenAIChat("gpt-5.6-sol").generate("hi")
    assert "reasoning_effort" not in seen and seen["_timeout"] == 300
    L.OpenAIChat("gpt-4o").generate("hi", effort="high")
    assert "reasoning_effort" not in seen        # 非 reasoning：跳过而非 400


def test_from_config_tier_routing(monkeypatch):
    """模型分层：flash 用 model_flash，未配则退回主模型；默认 pro。"""
    from joblander.llm import from_config

    class C:
        raw = {"llm": {"provider": "openai", "model": "big-model", "model_flash": "small-model"}}
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert from_config(C()).model == "big-model"
    assert from_config(C(), "pro").model == "big-model"
    assert from_config(C(), "flash").model == "small-model"

    class C2:
        raw = {"llm": {"provider": "openai", "model": "only-model"}}
    assert from_config(C2(), "flash").model == "only-model"

    class C3:
        raw = {"llm": {"provider": "openai"}}
    assert from_config(C3(), "flash").model == "gpt-5.6-luna"
    assert from_config(C3(), "pro").model == "gpt-5.6-sol"


def test_openai_base_url_routes_to_proxy(monkeypatch):
    """云端版：OPENAI_BASE_URL 指向计量代理，请求发去代理而不是 api.openai.com。"""
    from joblander import llm as L

    seen: dict = {}
    monkeypatch.setattr(L, "_http_sse_text",
                        lambda url, body, headers, timeout=300: seen.update(url=url) or "ok")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-sub")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://meter.internal:4000/v1/")
    L.OpenAIChat("gpt-5.6-sol").generate("hi")
    assert seen["url"] == "http://meter.internal:4000/v1/chat/completions"
    monkeypatch.delenv("OPENAI_BASE_URL")
    L.OpenAIChat("gpt-5.6-sol").generate("hi")
    assert seen["url"] == L.OpenAIChat.URL


def test_proxy_budget_rejection_becomes_quota_exceeded(monkeypatch):
    """代理按额度拒绝 ≠ 故障：转成 QuotaExceeded，给用户看得懂的提示。其他 4xx 原样抛。"""
    from joblander import llm as L

    def over(url, body, headers, timeout=300):
        raise LLMError('400: {"error":{"message":"Budget has been exceeded! Current cost: 2.01",'
                       '"type":"budget_exceeded"}}')
    monkeypatch.setattr(L, "_http_sse_text", over)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-sub")
    with pytest.raises(L.QuotaExceeded, match="额度已用完"):
        L.OpenAIChat("gpt-5.6-sol").generate("hi")

    monkeypatch.setattr(L, "_http_sse_text",
                        lambda *a, **k: (_ for _ in ()).throw(LLMError("400: bad request")))
    with pytest.raises(LLMError) as ei:
        L.OpenAIChat("gpt-5.6-sol").generate("hi")
    assert not isinstance(ei.value, L.QuotaExceeded)


def test_cloud_search_goes_through_gateway(monkeypatch):
    """云端版：没配 search 段、有 JOBLANDER_SEARCH_URL → 走网关代搜，带子 key；额度用完给人话。"""
    import io
    from joblander import search as S
    from joblander.config import Config

    seen = {}

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake_open(req, timeout=0):
        seen.update(url=req.full_url, auth=req.headers.get("Authorization"))
        return R(json.dumps({"results": [{"title": "t", "url": "u", "snippet": "s"}]}).encode())

    monkeypatch.setenv("JOBLANDER_SEARCH_URL", "http://gw.internal:8081/v1/search")
    monkeypatch.setenv("OPENAI_API_KEY", "jlm-sub")
    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    cfg = Config(raw={}, path=None)
    assert S.web_search(cfg, "Acme 融资")[0]["url"] == "u"
    assert seen == {"url": "http://gw.internal:8081/v1/search", "auth": "Bearer jlm-sub"}

    import urllib.error
    def over(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 400, "x", {},
                                     io.BytesIO(b'{"error":{"message":"Budget has been exceeded"}}'))
    monkeypatch.setattr("urllib.request.urlopen", over)
    with pytest.raises(S.SearchError, match="额度已用完"):
        S.web_search(cfg, "Acme")
