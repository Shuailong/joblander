"""W0 冷启动 — 配置完备性体检 + 三层理解脚手架（路径 B 的可执行入口）。

路径 A（战役中途接入）由迁移流程人工执行过（MIGRATION.md M0–M4）；
本模块给从零用户：检查缺什么、生成待填模板、指出下一步。
"""

from __future__ import annotations

from pathlib import Path

CHECKS = [
    ("workspace_dir", lambda c: c.raw.get("workspace_dir"), "设置私有 workspace 目录"),
    ("policy", lambda c: c.raw.get("policy", {}).get("quote_tc_sgd"), "填 policy：报价锚点等（三层理解·策略层）"),
    ("sentinel", lambda c: c.sentinel_rules, "填 sentinel.rules：红线词表（三层理解·红线层）"),
    ("llm", lambda c: c.raw.get("llm", {}).get("provider"), "选 LLM provider 并配 API key 环境变量"),
    ("notion", lambda c: c.raw.get("notion", {}).get("token"), "（可选）Notion integration token → tracker 投影"),
    ("gmail", lambda c: c.raw.get("gmail", {}).get("client_id"), "（可选）GCP OAuth client → gmail-scan 自动 sourcing"),
]

SCAFFOLD_DIRS = ["06-transcripts", "08-events", "09-projections", "10-briefs",
                 "11-shadow", "12-intake", "13-daily", "14-dossiers", "15-offers", "16-audits"]

PROFILE_TEMPLATE = """# 事实层（profile index）—— 填入你的硬事实与战绩
## 硬事实卡
| 项 | 值 |
|---|---|
| 任期/离职性质 | |
| 可到岗时间 | |
## 战绩索引（数字逐字，不许现场回忆）
| ID | 一句话 | 关键数字 |
|---|---|---|
"""


def onboard(cfg) -> str:
    lines = ["# W0 冷启动体检", ""]
    ok = missing = 0
    for name, probe, hint in CHECKS:
        try:
            val = probe(cfg)
        except Exception:
            val = None
        if val:
            ok += 1
            lines.append(f"- ✅ {name}")
        else:
            missing += 1
            lines.append(f"- ⬜ {name} —— {hint}")

    ws = cfg.workspace_dir
    created = []
    for d in SCAFFOLD_DIRS:
        p = ws / d
        if not p.exists():
            p.mkdir(parents=True)
            created.append(d)
    profile = ws / "03-materials"
    profile.mkdir(exist_ok=True)
    tpl = profile / "profile-index.md"
    if not tpl.exists():
        tpl.write_text(PROFILE_TEMPLATE, encoding="utf-8")
        created.append("03-materials/profile-index.md（模板）")
    # 空战线投影：Notion 可选，纯本地用户永远不跑 pull——没有这个文件
    # 作战室与 daily/weekly 都会拿「投影不存在」当错误报。
    proj = ws / "09-projections" / "tracker.json"
    if not proj.exists():
        proj.parent.mkdir(parents=True, exist_ok=True)
        proj.write_text('{"rows": []}\n', encoding="utf-8")
        created.append("09-projections/tracker.json（空战线）")

    lines += ["", f"配置：{ok} 就绪 / {missing} 待办"]
    if created:
        lines += ["脚手架已建：" + "、".join(created)]
    lines += ["", "下一步：`joblander web` 开作战室；有 Notion 先 `joblander pull` 拉战线，"
                  "没有就直接在「新机会」页录第一条线索"]
    return "\n".join(lines)
