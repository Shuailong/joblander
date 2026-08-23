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
    p = Path(path or os.environ.get("JOBLANDER_CONFIG") or REPO_ROOT / "config.yaml")
    if not p.exists():
        raise ConfigError(
            f"找不到配置文件：{p}（复制 config.example.yaml 为 config.yaml 后填入真实值）"
        )
    with open(p, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Config(raw=raw, path=p)
