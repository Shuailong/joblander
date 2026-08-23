"""Event Log 单测。"""

from joblander.eventlog import EventLog


def test_append_and_read(tmp_path):
    log = EventLog(tmp_path / "log.jsonl")
    e = log.append("test.event", "unit", {"a": 1})
    assert e["kind"] == "test.event" and e["ts"]
    events = list(log.events())
    assert len(events) == 1
    assert events[0]["payload"] == {"a": 1}


def test_append_preserves_order_and_tail(tmp_path):
    log = EventLog(tmp_path / "log.jsonl")
    for i in range(5):
        log.append("k", "unit", {"i": i})
    assert log.count() == 5
    assert [e["payload"]["i"] for e in log.tail(2)] == [3, 4]


def test_explicit_ts_and_unicode(tmp_path):
    log = EventLog(tmp_path / "log.jsonl")
    log.append("k", "unit", {"公司": "测试"}, ts="2026-08-07T00:00:00+08:00")
    e = list(log.events())[0]
    assert e["ts"] == "2026-08-07T00:00:00+08:00"
    assert e["payload"]["公司"] == "测试"


def test_missing_file_yields_nothing(tmp_path):
    log = EventLog(tmp_path / "nope.jsonl")
    assert list(log.events()) == []
