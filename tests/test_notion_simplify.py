"""simplify_page 单测 —— 合成 Notion page 对象，公开可跑。"""

from joblander.notion import simplify_page

PAGE = {
    "id": "abc-123",
    "url": "https://notion.so/abc123",
    "last_edited_time": "2026-08-07T00:00:00.000Z",
    "properties": {
        "Company": {"type": "title", "title": [{"plain_text": "Acme"}, {"plain_text": " AI"}]},
        "Position": {"type": "rich_text", "rich_text": [{"plain_text": "Engineer"}]},
        "Status": {"type": "status", "status": {"name": "Applied"}},
        "Priority": {"type": "select", "select": None},
        "Follow-up Reminder": {"type": "date", "date": {"start": "2026-08-12"}},
        "Job URL": {"type": "url", "url": None},
        "Notes": {"type": "rich_text", "rich_text": []},
    },
}


def test_simplify_basic_fields():
    row = simplify_page(PAGE)
    assert row["notion_page_id"] == "abc-123"
    assert row["Company"] == "Acme AI"
    assert row["Position"] == "Engineer"
    assert row["Status"] == "Applied"


def test_simplify_null_handling():
    row = simplify_page(PAGE)
    assert row["Priority"] is None          # select 为空
    assert row["Job URL"] is None
    assert row["Notes"] is None             # 空 rich_text → None
    assert row["Follow-up Reminder"] == "2026-08-12"
