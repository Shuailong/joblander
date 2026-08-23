"""LLM 抽象层（ADR-7）：引擎不绑供应商。

P0 实际在用：openai（本机已有 key）；gemini 为 P3 GCP 目标实现；mock 供测试。
API key 永远从环境变量读，不落任何配置文件。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol


class LLMError(RuntimeError):
    pass


USAGE = {"prompt": 0, "completion": 0, "calls": 0}   # 进程内累计（OpenAI 流式回报），成本测量用


class LLMClient(Protocol):
    def generate(self, prompt: str, system: str | None = None, json_mode: bool = False,
                 effort: str | None = None) -> str: ...


class MockLLM:
    """测试用：按序返回预置响应，并记录调用。"""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, prompt: str, system: str | None = None, json_mode: bool = False,
                 effort: str | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system, "json_mode": json_mode,
                           "effort": effort})
        if not self.responses:
            raise LLMError("MockLLM 响应用尽")
        return self.responses.pop(0)


def _http_json(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise LLMError(f"{e.code}: {e.read().decode(errors='replace')[:300]}") from e


def _http_sse_text(url: str, body: dict, headers: dict, timeout: int = 300) -> str:
    """OpenAI streaming：逐行读 SSE 拼 delta。长生成（大 prompt/大输出）的非流式
    请求会在响应就绪前 TCP 静默几十秒，被网络中间层当 idle 掐掉（实测 Errno 54）；
    流式连接始终有字节流动，不会被掐。"""
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Accept": "text/event-stream", **headers})
    parts: list[str] = []
    try:
        # 默认 300：reasoning 系模型首 token 前有静默思考期，120s 会误杀；
        # reasoning_effort=high 思考更久，调用方按需放宽
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if obj.get("usage"):
                    USAGE["prompt"] += obj["usage"].get("prompt_tokens") or 0
                    USAGE["completion"] += obj["usage"].get("completion_tokens") or 0
                    USAGE["calls"] += 1
                delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                if delta.get("content"):
                    parts.append(delta["content"])
    except urllib.error.HTTPError as e:
        raise LLMError(f"{e.code}: {e.read().decode(errors='replace')[:300]}") from e
    return "".join(parts)


def _with_retry(fn, tries: int = 3):
    """网络级瞬断（连接重置/超时）重试；HTTP 4xx（LLMError）不重试。"""
    import time
    last: Exception | None = None
    for i in range(tries):
        try:
            return fn()
        except LLMError:
            raise
        except (ConnectionError, urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if i < tries - 1:
                time.sleep(2 * (i + 1))
    raise LLMError(f"网络错误（重试 {tries} 次后放弃）：{last}") from last


class OpenAIChat:
    URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, model: str, api_key: str | None = None, temperature: float = 0.2):
        self.model = model
        self.temperature = temperature
        self.key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.key:
            raise LLMError("缺 OPENAI_API_KEY 环境变量")

    def generate(self, prompt: str, system: str | None = None, json_mode: bool = False,
                 effort: str | None = None) -> str:
        messages = ([{"role": "system", "content": system}] if system else [])
        messages.append({"role": "user", "content": prompt})
        body: dict = {"model": self.model, "messages": messages, "stream": True,
                      "stream_options": {"include_usage": True}}
        # gpt-5/o 系 reasoning 模型只接受默认温度，传值即 400；-chat 变体不受限
        reasoning = self.model.startswith(("gpt-5", "o3", "o4")) and "-chat" not in self.model
        if not reasoning:
            body["temperature"] = self.temperature
        elif effort:                              # 非 reasoning 模型传该参会 400，静默跳过
            body["reasoning_effort"] = effort
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return _with_retry(lambda: _http_sse_text(
            self.URL, body, {"Authorization": f"Bearer {self.key}"},
            timeout=600 if effort == "high" else 300))


class GeminiChat:
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, model: str, api_key: str | None = None, temperature: float = 0.2):
        self.model = model
        self.temperature = temperature
        self.key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.key:
            raise LLMError("缺 GEMINI_API_KEY 环境变量")

    def generate(self, prompt: str, system: str | None = None, json_mode: bool = False,
                 effort: str | None = None) -> str:
        # effort 暂不映射（Gemini thinking 配置等 P3 真用到再接），仅保签名兼容
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": self.temperature},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        url = self.URL.format(model=self.model) + f"?key={self.key}"
        data = _with_retry(lambda: _http_json(url, body, {}))
        return data["candidates"][0]["content"]["parts"][0]["text"]


def from_config(cfg, tier: str = "pro") -> LLMClient:
    """tier 模型分层（§8.4 简化版）：
    - "pro"   质量敏感：复盘、简历定制、公司评估、能力画像、周报、调研
    - "flash" 高频/结构化：抽取、初筛、扫描分类、字段建议、日记草稿
    - "eval"  评测裁判：永远用得起的最强模型——评产物的模型不能弱于产产物的
    未配置 model_flash/model_eval 时退回主模型——单模型用户行为不变。
    """
    llm_cfg = cfg.raw.get("llm", {})
    provider = llm_cfg.get("provider", "openai")
    model = llm_cfg.get("model")
    if tier == "flash":
        model = llm_cfg.get("model_flash") or model
    elif tier == "eval":
        model = llm_cfg.get("model_eval") or model
    if provider == "openai":
        default = "gpt-5.6-luna" if tier == "flash" else "gpt-5.6-sol"
        return OpenAIChat(model or default)
    if provider == "gemini":
        return GeminiChat(model or "gemini-2.0-flash")
    raise LLMError(f"未知 provider：{provider}（mock 仅限测试内直接构造）")
