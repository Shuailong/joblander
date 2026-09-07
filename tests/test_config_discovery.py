"""配置查找顺序：显式路径 > $JOBLANDER_CONFIG > 当前目录 > REPO_ROOT。

当前目录这一跳是 2026-09-07 干净沙箱实测补的：非 editable 安装（`pip install .`）时
REPO_ROOT 落在 site-packages，用户照 README 在自己 clone 目录里建的 config.yaml
会被完全无视——装完第一条命令 onboard 就崩，且报错路径指向 site-packages 让人摸不着头脑。
"""

import pytest
import yaml

from joblander.config import ConfigError, load_config


def _write(p, workspace):
    p.write_text(yaml.safe_dump({"workspace_dir": str(workspace)}), encoding="utf-8")


def test_cwd_config_found_when_repo_root_has_none(tmp_path, monkeypatch):
    """当前目录的 config.yaml 必须被找到——这是非 editable 安装的唯一可用路径。"""
    monkeypatch.delenv("JOBLANDER_CONFIG", raising=False)
    monkeypatch.setattr("joblander.config.REPO_ROOT", tmp_path / "nowhere")
    _write(tmp_path / "config.yaml", tmp_path / "ws")
    monkeypatch.chdir(tmp_path)

    cfg = load_config()
    assert cfg.path == tmp_path / "config.yaml"
    assert cfg.workspace_dir == tmp_path / "ws"


def test_explicit_path_and_env_beat_cwd(tmp_path, monkeypatch):
    """显式路径与环境变量优先级高于当前目录，不被 cwd 抢走。"""
    monkeypatch.setattr("joblander.config.REPO_ROOT", tmp_path / "nowhere")
    _write(tmp_path / "config.yaml", tmp_path / "ws-cwd")
    _write(tmp_path / "other.yaml", tmp_path / "ws-other")
    monkeypatch.chdir(tmp_path)

    monkeypatch.delenv("JOBLANDER_CONFIG", raising=False)
    assert load_config(tmp_path / "other.yaml").workspace_dir == tmp_path / "ws-other"

    monkeypatch.setenv("JOBLANDER_CONFIG", str(tmp_path / "other.yaml"))
    assert load_config().workspace_dir == tmp_path / "ws-other"


def test_repo_root_still_works_for_source_checkout(tmp_path, monkeypatch):
    """editable / 源码签出：cwd 没有 config 时仍回落到 REPO_ROOT，老行为不破。"""
    monkeypatch.delenv("JOBLANDER_CONFIG", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    _write(root / "config.yaml", tmp_path / "ws-root")
    monkeypatch.setattr("joblander.config.REPO_ROOT", root)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert load_config().workspace_dir == tmp_path / "ws-root"


def test_missing_config_error_mentions_env_var(tmp_path, monkeypatch):
    """两处都没有时报错要给出可行的下一步（含 JOBLANDER_CONFIG 出路）。"""
    monkeypatch.delenv("JOBLANDER_CONFIG", raising=False)
    monkeypatch.setattr("joblander.config.REPO_ROOT", tmp_path / "nowhere")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigError, match="JOBLANDER_CONFIG"):
        load_config()
