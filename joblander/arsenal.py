"""弹药库：achievement-bank.md 的按段读写层。

SoT 仍是 03-materials/achievement-bank.md（brief / 能力画像 / 简历生成都整读它，
格式不动它们无感）。本模块只做：按 `## ` 拆段 → 页面按段编辑 → 原位重组写回。

「素材使用注意」类段落是内部规则不是素材——生成简历/brief/策略时照常进语料，
但弹药库页面不展示（internal=True）。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

SGT = timezone(timedelta(hours=8))
INTERNAL_PAT = re.compile(r"使用注意|注意事项|内部规则")


def bank_path(cfg) -> Path:
    return cfg.workspace_dir / "03-materials" / "achievement-bank.md"


def load_sections(cfg) -> dict:
    """拆成 preamble（首个 ## 前的文件头）+ sections[{idx,title,body,internal}]。"""
    p = bank_path(cfg)
    if not p.exists():
        return {"preamble": "", "sections": []}
    preamble: list[str] = []
    sections: list[dict] = []
    cur: dict | None = None
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            title = line[3:].strip()
            cur = {"idx": len(sections), "title": title, "body_lines": [],
                   "internal": bool(INTERNAL_PAT.search(title))}
            sections.append(cur)
        elif cur is None:
            preamble.append(line)
        else:
            cur["body_lines"].append(line)
    for s in sections:
        s["body"] = "\n".join(s.pop("body_lines")).strip("\n")
    return {"preamble": "\n".join(preamble).rstrip(), "sections": sections}


def _write(cfg, data: dict) -> None:
    parts = [data["preamble"].rstrip()] if data["preamble"].strip() else []
    for s in data["sections"]:
        parts.append(f"## {s['title'].strip()}\n\n{s['body'].strip()}")
    bank_path(cfg).write_text("\n\n".join(parts) + "\n", encoding="utf-8")


def _log(cfg, event: str, payload: dict) -> None:
    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        event, "human_direct", payload)


def save_section(cfg, idx: int, title: str, body: str, orig_title: str = "") -> None:
    """按位置改段；orig_title 校验防两窗并发把别人的段覆盖掉。"""
    data = load_sections(cfg)
    if not (0 <= idx < len(data["sections"])):
        raise ValueError(f"段落 #{idx} 不存在——刷新页面再试")
    cur = data["sections"][idx]
    if orig_title and cur["title"] != orig_title:
        raise ValueError(f"段落已在别处变动（现为「{cur['title']}」）——刷新页面再试")
    if not title.strip() or not body.strip():
        raise ValueError("标题和内容都不能为空")
    cur["title"], cur["body"] = title.strip(), body
    _write(cfg, data)
    _log(cfg, "arsenal.section_saved", {"idx": idx, "title": title.strip()[:80]})


def add_section(cfg, title: str, body: str) -> None:
    """新素材段插在首个内部段（使用注意）之前——素材归素材，规则永远垫底。"""
    if not title.strip() or not body.strip():
        raise ValueError("标题和内容都不能为空")
    data = load_sections(cfg)
    if any(s["title"].strip() == title.strip() for s in data["sections"]):
        raise ValueError(f"已有同名段落「{title.strip()}」——去那一段里编辑")
    at = next((i for i, s in enumerate(data["sections"]) if s["internal"]),
              len(data["sections"]))
    data["sections"].insert(at, {"title": title.strip(), "body": body,
                                 "internal": False})
    _write(cfg, data)
    _log(cfg, "arsenal.section_added", {"title": title.strip()[:80]})


def delete_section(cfg, idx: int, title: str) -> None:
    """删素材段。内部规则段（使用注意）不可删——红线纪律不给 UI 误伤的机会。
    title 校验防两窗并发把别人的段删掉。"""
    data = load_sections(cfg)
    if not (0 <= idx < len(data["sections"])):
        raise ValueError(f"段落 #{idx} 不存在——刷新页面再试")
    cur = data["sections"][idx]
    if cur["title"].strip() != title.strip():
        raise ValueError(f"段落已在别处变动（现为「{cur['title']}」）——刷新页面再试")
    if cur["internal"]:
        raise ValueError("内部规则段不可删除")
    data["sections"].pop(idx)
    _write(cfg, data)
    _log(cfg, "arsenal.section_deleted", {"title": title.strip()[:80]})


def reorder_sections(cfg, titles: list[str]) -> None:
    """按给定标题序重排非内部段；内部规则段永远垫底（相对序不动）。
    清单必须与当前非内部段一一对应——防拿着旧页面的顺序覆盖新状态。"""
    data = load_sections(cfg)
    normal = [s for s in data["sections"] if not s["internal"]]
    internal = [s for s in data["sections"] if s["internal"]]
    by_title = {s["title"]: s for s in normal}
    want = [t.strip() for t in titles]
    if sorted(want) != sorted(by_title):
        raise ValueError("段落清单与当前不一致——刷新页面再试")
    data["sections"] = [by_title[t] for t in want] + internal
    _write(cfg, data)
    _log(cfg, "arsenal.sections_reordered", {"order": [t[:40] for t in want]})
