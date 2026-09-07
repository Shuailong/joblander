"""Config loader.

私有 config.yaml（gitignored）承载所有真实数字与词表；引擎代码零硬编码（DESIGN §13 公私边界）。
查找顺序：显式路径 > $JOBLANDER_CONFIG > 仓库根 config.yaml。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


class ConfigError(RuntimeError):
    pass


@dataclass
class Config:
    raw: dict[str, Any]
    path: Path

    @property
    def workspace_dir(self) -> Path:
        d = self.raw.get("workspace_dir")
        if not d:
            raise ConfigError("config 缺少 workspace_dir")
        return Path(d)

    @property
    def policy(self) -> dict[str, Any]:
        return self.raw.get("policy", {})

    @property
    def sentinel_rules(self) -> list[dict[str, Any]]:
        return self.raw.get("sentinel", {}).get("rules", [])


def load_config(path: str | Path | None = None) -> Config:
    explicit = path or os.environ.get("JOBLANDER_CONFIG")
    if explicit:
        p = Path(explicit)
    else:
        # 当前目录优先于 REPO_ROOT：非 editable 安装时 REPO_ROOT 落在 site-packages，
        # 用户在自己 clone 目录里建的 config.yaml 会被无视（装完 onboard 就崩）。
        candidates = [Path.cwd() / "config.yaml", REPO_ROOT / "config.yaml"]
        p = next((c for c in candidates if c.exists()), candidates[0])
    if not p.exists():
        raise ConfigError(
            f"找不到配置文件：{p}（复制 config.example.yaml 为 config.yaml 后填入真实值；"
            f"也可用 JOBLANDER_CONFIG 环境变量指定路径）"
        )
    with open(p, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Config(raw=raw, path=p)
