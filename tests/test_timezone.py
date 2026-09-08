"""本地时区单一来源。

2026-09-08：此前 28 个模块各写一遍 SGT = timezone(timedelta(hours=8))，
「今天」的边界、日报/周报文件名、daemon 的 08:15/21:30/02:30 全钉死在 UTC+8——
非 UTC+8 的用户拿到的是一套对不上自己一天的时钟，且没有任何开关。
"""

import importlib
from datetime import timedelta, timezone

import pytest

import joblander.tz as tzmod


def _reload(monkeypatch, spec):
    if spec is None:
        monkeypatch.delenv("JOBLANDER_TZ", raising=False)
    else:
        monkeypatch.setenv("JOBLANDER_TZ", spec)
    return importlib.reload(tzmod).LOCAL_TZ


def test_default_is_unchanged_utc8(monkeypatch):
    """不设环境变量必须与历史行为逐字一致。"""
    assert _reload(monkeypatch, None) == timezone(timedelta(hours=8))


@pytest.mark.parametrize("spec,offset", [
    ("+05:30", timedelta(hours=5, minutes=30)),
    ("+0530", timedelta(hours=5, minutes=30)),
    ("-05:00", timedelta(hours=-5)),
    ("+00:00", timedelta(0)),
])
def test_fixed_offsets(monkeypatch, spec, offset):
    assert _reload(monkeypatch, spec).utcoffset(None) == offset


def test_iana_name(monkeypatch):
    tz = _reload(monkeypatch, "Europe/Berlin")
    assert "Berlin" in str(tz)


def test_garbage_falls_back_instead_of_crashing(monkeypatch):
    """名字打错不该让整个程序起不来。"""
    assert _reload(monkeypatch, "Not/AZone") == timezone(timedelta(hours=8))
    assert _reload(monkeypatch, "垃圾") == timezone(timedelta(hours=8))


def test_no_module_redefines_the_timezone():
    """回归：不许有人再写一遍 hours=8——单一来源才有意义。"""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for f in list((root / "joblander").rglob("*.py")) + list((root / "evals").rglob("*.py")):
        if f.name == "tz.py":
            continue
        if "hours=8" in f.read_text(encoding="utf-8"):
            offenders.append(str(f.relative_to(root)))
    assert not offenders, f"这些文件又把时区写死了：{offenders}"


def teardown_module():
    importlib.reload(tzmod)          # 别把改过的模块状态留给后面的用例
