"""界面多语言：中文原文即键（gettext 式），英文查 EN 表；缺译回落中文，不会出空白。

- 模板里 `{{ _('新机会') }}`；带变量的 `{{ _('待入池（{n} 岗）', n=total) }}`
- JS 字符串上下文用 `{{ _('已保存')|jsq }}`：输出单引号 JS 字面量，可安全嵌进 onclick="…"
- 当前语言放 contextvar，由 web 中间件按请求设置：config 的 ui_lang 优先，否则看浏览器
"""

from __future__ import annotations

import contextvars
import json

from joblander.web.i18n_en import EN

LANGS = ("zh", "en")
_lang: contextvars.ContextVar[str] = contextvars.ContextVar("ui_lang", default="zh")


def set_lang(lang: str) -> None:
    _lang.set(lang if lang in LANGS else "zh")


def get_lang() -> str:
    return _lang.get()


def pick_lang(configured: str | None, accept_language: str | None) -> str:
    if configured in LANGS:
        return configured
    first = (accept_language or "").split(",")[0].strip().lower()
    return "en" if first.startswith("en") else "zh"


def _(text: str, **kw) -> str:
    out = EN.get(text, text) if _lang.get() == "en" else text
    return out.format(**kw) if kw else out


def jsq(s: str):
    """单引号 JS 字符串字面量，同时可放进 onclick="…" 属性与 <script> 块：
    引号与 HTML 特殊字符全转成 \\xNN，两种上下文都不用再转义（故返回 Markup）。"""
    from markupsafe import Markup
    body = json.dumps(str(s), ensure_ascii=False)[1:-1].replace('\\"', '"')
    for ch, esc in (("'", "\\x27"), ('"', "\\x22"), ("<", "\\x3c"), (">", "\\x3e"), ("&", "\\x26")):
        body = body.replace(ch, esc)
    return Markup("'" + body + "'")


# app.js 里的文案（静态文件拿不到 _()，英文界面时由 base.html 注入 window.I18N）
JS_STRINGS = {k: EN[k] for k in ("任务", "进行中——右下角看进度", "完成", "失败：", " 完成", " 失败：")}
