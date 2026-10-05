"""代码拼出来的内容（时间线标题、报告骨架、提示语）跟着输出语言走。

LLM 写的部分由 llm.OutputLanguage 统一管；这里管的是 Python 自己写死的那些字。
语言只认配置（ui_lang）：后台任务与夜扫没有浏览器请求可看。
"""

from __future__ import annotations


def lang_of(cfg) -> str:
    from joblander.llm import output_lang
    return output_lang(cfg)


def pick(lang: str, zh: str, en: str) -> str:
    return en if lang == "en" else zh
