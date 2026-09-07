"""CLI 顶层错误呈现：可预期的问题给一行人话，bug 才甩栈。

2026-09-07 干净沙箱实测补的：没配 API key 时 `joblander intake` 吐一屏栈帧，
最底下才是「缺 OPENAI_API_KEY 环境变量」——信息对，但新用户第一反应是「装坏了」。
"""

import pytest

from joblander.__main__ import main
from joblander.config import ConfigError
from joblander.llm import LLMError


@pytest.mark.parametrize("exc", [
    ConfigError("找不到配置文件：/x/config.yaml"),
    LLMError("缺 OPENAI_API_KEY 环境变量"),
    FileNotFoundError("投影不存在：/x/tracker.json"),
])
def test_expected_failures_print_one_line(monkeypatch, capsys, exc):
    monkeypatch.setattr("joblander.__main__._run", lambda argv=None: (_ for _ in ()).throw(exc))

    code = main(["check", "x"])

    err = capsys.readouterr().err
    assert code == 1
    assert err.startswith("✗ ")
    assert "Traceback" not in err
    assert str(exc) in err


def test_unexpected_errors_still_raise(monkeypatch):
    """未预期异常不吞——那是 bug，栈要留给开发者。"""
    monkeypatch.setattr("joblander.__main__._run",
                        lambda argv=None: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        main(["check", "x"])


def test_check_command_still_works(tmp_path, monkeypatch, capsys):
    """包一层之后正常路径不受影响：规则层拦截照旧。"""
    from joblander.config import Config
    cfg = Config(raw={"workspace_dir": str(tmp_path),
                      "sentinel": {"rules": [{"id": "codename", "type": "pattern",
                                              "action": "block", "patterns": ["ProjectX"]}]}},
                 path=tmp_path / "c.yaml")
    monkeypatch.setattr("joblander.config.load_config", lambda *a, **k: cfg)

    assert main(["check", "we shipped ProjectX"]) == 0
    assert "BLOCK" in capsys.readouterr().out
