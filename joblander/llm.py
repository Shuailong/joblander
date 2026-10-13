"""LLM 抽象层（ADR-7）：引擎不绑供应商。

P0 实际在用：openai（本机已有 key）；gemini 为 P3 GCP 目标实现；mock 供测试。
API key 永远从环境变量读，不落任何配置文件。
"""

from __future__ import annotations

import contextvars
import json
import os
import urllib.error
import urllib.request
from typing import Protocol


class LLMError(RuntimeError):
    pass


class QuotaExceeded(LLMError):
    """计量代理（云端版）按用户额度拒绝了请求——不是故障，不重试，提示充值。"""


class PlatformPaused(LLMError):
    """计量代理（云端版）因平台当月 AI 总预算用完而拒绝——不是用户自己的额度，不重试。"""


# 云端版：当前在做哪件事（网页请求的「方法 + 路由模板」/ 后台定时作业名），调模型时带给计量口，
# 计量口按它记每次调用的花费归属。只有路由模板与作业名，不含任何内容。
FEATURE: contextvars.ContextVar[str] = contextvars.ContextVar("joblander_feature", default="")


class RateLimited(LLMError):
    """上游限流（429）或临时故障（5xx）：等一会儿再试通常就好，由 _with_retry 退避重试。"""

    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


# 限流退避：等 10s → 30s → 60s 再试；上游给了 Retry-After 就照它（最多 60s）
RATE_WAITS = (10, 30, 60)


def _http_error(e: urllib.error.HTTPError) -> LLMError:
    body = e.read().decode(errors="replace")
    msg = f"{e.code}: {body[:300]}"
    if "platform_budget" in body:                # 平台当月总预算到顶：重试没用，也不是用户自己的额度
        return PlatformPaused("AI 服务暂停：平台本月的 AI 预算已用完，运营方已收到通知")
    if "insufficient_quota" in body:             # 平台账户没钱了：重试没用，说清楚是谁的问题
        return LLMError("AI 服务暂时不可用：平台的 OpenAI 账户额度耗尽，运营方已收到告警"
                        if os.environ.get("JOBLANDER_GATEWAY_TOKEN")
                        else f"OpenAI 账户额度耗尽（insufficient_quota），请到 OpenAI 后台充值：{msg}")
    if e.code == 429 or e.code in (500, 502, 503, 504):
        try:
            ra = float(e.headers.get("retry-after") or "") if e.headers else None
        except ValueError:
            ra = None
        return RateLimited(msg, ra)
    return LLMError(msg)


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
        raise _http_error(e) from e


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
        raise _http_error(e) from e
    return "".join(parts)


def _with_retry(fn, tries: int = 3):
    """网络级瞬断（连接重置/超时）重试 tries 次；限流 / 5xx（RateLimited）按 RATE_WAITS 退避重试；
    其余 HTTP 错误（LLMError）不重试。"""
    import time
    last: Exception | None = None
    waits = list(RATE_WAITS)
    i = 0
    while i < tries:
        try:
            return fn()
        except RateLimited as e:
            if not waits:
                raise LLMError("AI 服务繁忙（上游限流），自动重试几次仍没成功，请过几分钟再试") from e
            w = waits.pop(0)
            time.sleep(min(e.retry_after, 60) if e.retry_after else w)
            continue
        except LLMError:
            raise
        except (ConnectionError, urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            i += 1
            if i < tries:
                time.sleep(2 * i)
    raise LLMError(f"网络错误（重试 {tries} 次后放弃）：{last}") from last


def _is_budget_error(e: LLMError) -> bool:
    """LiteLLM 代理超预算时回 400，正文带 ExceededBudget / budget exceeded 字样。"""
    text = str(e).lower()
    return "exceededbudget" in text or ("budget" in text and "exceed" in text)


class OpenAIChat:
    URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, model: str, api_key: str | None = None, temperature: float = 0.2,
                 base_url: str | None = None):
        self.model = model
        self.temperature = temperature
        # 云端版走计量代理（OpenAI 兼容接口）：OPENAI_BASE_URL 指过去，key 是代理发的子 key
        base = base_url or os.environ.get("OPENAI_BASE_URL")
        if base:
            self.URL = base.rstrip("/") + "/chat/completions"
        self.metered = bool(base)                # 走计量代理才带功能标签，直连 OpenAI 不带
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
        headers = {"Authorization": f"Bearer {self.key}"}
        if self.metered and FEATURE.get():
            headers["X-Joblander-Feature"] = FEATURE.get()
        try:
            return _with_retry(lambda: _http_sse_text(
                self.URL, body, headers,
                timeout=600 if effort == "high" else 300))
        except LLMError as e:
            if not isinstance(e, PlatformPaused) and _is_budget_error(e):
                raise QuotaExceeded("AI 额度已用完——在「设置 › 账户」里申请更多额度"
                                    if os.environ.get("JOBLANDER_GATEWAY_TOKEN")
                                    else "AI 额度已用完——充值或订阅后继续使用") from e
            raise


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


# 英文界面时附加在每个 system prompt 末尾。提示词本身是中文写的，所以要点名：哪些照旧（JSON 键、
# 代码要比对的固定取值），哪些改英文（一切给人读的文字）。固定取值显示时由界面层再翻。
ENGLISH_OUTPUT = """

【OUTPUT LANGUAGE — overrides any language instruction above】
The user reads English. Write every human-readable string in natural, professional English:
summaries, explanations, reasons, flags, notes, drafts, headings, bullet points, markdown documents, resumes.
The instructions above are written in Chinese and contain Chinese example phrases (e.g. 中介代招,
『简历约 6 年，JD 要 8 年』) — those are illustrations: write their English equivalent, never copy the Chinese.
Keep EXACTLY as specified (do not translate) only:
- JSON keys and structure;
- values that the instructions define as a closed set of allowed options for a field, written like
  "verdict": "不符|存疑" or 达标/缺/死角 — copy the chosen option character for character;
- facts: names, companies, titles, numbers, dates, URLs, quoted source text."""

ENGLISH_PROMPT_TAIL = "\n\n(Answer in English, following the OUTPUT LANGUAGE rule in the system prompt.)"


class OutputLanguage:
    """给任意 LLMClient 套上输出语言指令；不改提示词本体，所有 Agent 一处生效。"""

    def __init__(self, inner: LLMClient, suffix: str):
        self.inner, self.suffix = inner, suffix
        self.model = getattr(inner, "model", "")

    def generate(self, prompt: str, system: str | None = None, json_mode: bool = False,
                 effort: str | None = None) -> str:
        return self.inner.generate(prompt + ENGLISH_PROMPT_TAIL, system=(system or "") + self.suffix,
                                   json_mode=json_mode, effort=effort)


def output_lang(cfg) -> str:
    return "en" if (cfg.raw.get("ui_lang") if cfg is not None else None) == "en" else "zh"


def from_config(cfg, tier: str = "pro") -> LLMClient:
    client = _from_config(cfg, tier)
    return OutputLanguage(client, ENGLISH_OUTPUT) if output_lang(cfg) == "en" else client


def _from_config(cfg, tier: str = "pro") -> LLMClient:
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
        return OpenAIChat(model or default, base_url=llm_cfg.get("base_url"))
    if provider == "gemini":
        return GeminiChat(model or "gemini-2.0-flash")
    raise LLMError(f"未知 provider：{provider}（mock 仅限测试内直接构造）")
