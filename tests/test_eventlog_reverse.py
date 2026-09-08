"""事件日志倒序读取 —— 日志只增不减，「取最近 N 条」不能靠把整份读进内存。

2026-09-08：此前 tail() 是 list(events())[-n:]，/system 的 mcf_last 更是
reversed(list(events()))，成本随使用时间线性增长且永不回落。
"""

import json

import pytest

from joblander.eventlog import EventLog


@pytest.fixture
def log(tmp_path):
    lg = EventLog(tmp_path / "e.jsonl")
    for i in range(200):
        lg.append("kind.b" if i % 3 == 0 else "kind.a", "t", {"i": i})
    return lg


def test_reverse_yields_newest_first_and_complete(log):
    got = [e["payload"]["i"] for e in log.iter_reversed()]
    assert got == list(range(199, -1, -1))


@pytest.mark.parametrize("chunk", [4, 7, 64, 65536])
def test_reverse_survives_chunk_boundaries(log, chunk):
    """半行会跨 chunk：拼接错就会丢条目或产生坏 JSON。"""
    assert len(list(log.iter_reversed(chunk=chunk))) == 200


def test_tail_matches_forward_semantics(log):
    fwd = list(log.events())
    assert log.tail(5) == fwd[-5:]          # 对外仍是旧→新
    assert log.tail(1000) == fwd            # n 超总数给全部


def test_last_finds_newest_of_kind(log):
    assert log.last("kind.b")["payload"]["i"] == 198
    assert log.last("kind.nonexistent") is None


def test_handles_empty_missing_and_corrupt(tmp_path):
    missing = EventLog(tmp_path / "none.jsonl")
    assert missing.tail(3) == [] and missing.last("x") is None

    p = tmp_path / "mix.jsonl"
    p.write_text('{"kind":"a","ts":"1","source":"s","payload":{}}\n'
                 '{坏行\n'
                 '{"kind":"b","ts":"2","source":"s","payload":{}}', encoding="utf-8")  # 末尾无换行
    lg = EventLog(p)
    kinds = [e["kind"] for e in lg.iter_reversed()]
    assert kinds == ["b", "a"], "坏行该跳过，末行无换行也要读到"


def test_system_stats_cache_matches_full_scan_and_invalidates(tmp_path):
    from joblander.web.app import _log_stats
    lg = EventLog(tmp_path / "s.jsonl")
    for i in range(50):
        lg.append("job.failed" if i % 5 == 0 else "other", "t", {"i": i})

    def naive():
        n, kinds = 0, {}
        for e in lg.events():
            n += 1
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        return n, kinds

    assert _log_stats(lg) == naive()
    assert _log_stats(lg) == naive()        # 缓存命中，结果不变
    lg.append("brand.new", "t", {})
    n, kinds = _log_stats(lg)
    assert n == 51 and "brand.new" in kinds, "追加后指纹该失效"
