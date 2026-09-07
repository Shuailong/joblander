"""Notion 读取器（P0：只读）。

职责：tracker 全量拉取 → 扁平化行 → 本地投影文件 + tracker.pulled 事件。
写回（提案制）在后续批次；本模块永不直接写 Notion（P6/ADR-2）。

依赖：仅 stdlib（urllib）。API 版本优先用 data_sources 端点，失败回退 legacy databases 端点。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Iterator

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"          # data_sources 端点
NOTION_VERSION_LEGACY = "2022-06-28"   # databases 端点回退


class NotionError(RuntimeError):
    pass


class NotionClient:
    def __init__(self, token: str, version: str = NOTION_VERSION):
        self.token = token
        self.version = version

    def _request(self, method: str, path: str, body: dict | None = None,
                 version: str | None = None) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{API_BASE}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": version or self.version,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            raise NotionError(f"{e.code} {path}: {detail}") from e

    def iter_rows(self, data_source_id: str, database_id: str | None = None) -> Iterator[dict]:
        """分页拉取全部行。先试 data_sources 端点，404/400 时回退 legacy databases 端点。"""
        cursor: str | None = None
        use_legacy = False
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            try:
                if not use_legacy:
                    page = self._request("POST", f"/data_sources/{data_source_id}/query", body)
                else:
                    page = self._request(
                        "POST", f"/databases/{database_id or data_source_id}/query",
                        body, version=NOTION_VERSION_LEGACY)
            except NotionError as e:
                if not use_legacy and database_id and ("404" in str(e) or "400" in str(e)):
                    use_legacy = True
                    continue
                raise
            yield from page.get("results", [])
            if not page.get("has_more"):
                return
            cursor = page.get("next_cursor")

    # ---- 页面正文（只读） ----

    _TEXT_BLOCKS = ("paragraph", "heading_1", "heading_2", "heading_3",
                    "bulleted_list_item", "numbered_list_item", "quote", "callout", "toggle", "to_do")

    def page_body_text(self, page_id: str, max_blocks: int = 300) -> str:
        """页面正文 → 纯文本（v0 不递归子块）。"""
        lines: list[str] = []
        cursor: str | None = None
        while len(lines) < max_blocks:
            path = f"/blocks/{page_id}/children?page_size=100"
            if cursor:
                path += f"&start_cursor={cursor}"
            page = self._request("GET", path)
            for block in page.get("results", []):
                btype = block.get("type")
                if btype not in self._TEXT_BLOCKS:
                    continue
                text = _plain(block[btype].get("rich_text", []))
                if not text.strip():
                    continue
                prefix = {"heading_1": "# ", "heading_2": "## ", "heading_3": "### ",
                          "bulleted_list_item": "- ", "numbered_list_item": "- ",
                          "quote": "> ", "to_do": "- [ ] "}.get(btype, "")
                lines.append(prefix + text)
            if not page.get("has_more"):
                break
            cursor = page.get("next_cursor")
        return "\n".join(lines)

    def page_files(self, page_id: str, max_blocks: int = 300) -> list[dict[str, Any]]:
        """页面里的文件/PDF 附件块 → [{name, url}]（url 为 S3 签名链接，短时有效）。"""
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        seen = 0
        while seen < max_blocks:
            path = f"/blocks/{page_id}/children?page_size=100"
            if cursor:
                path += f"&start_cursor={cursor}"
            page = self._request("GET", path)
            for block in page.get("results", []):
                seen += 1
                btype = block.get("type")
                if btype not in ("file", "pdf"):
                    continue
                payload = block.get(btype) or {}
                fobj = payload.get("file") or payload.get("external") or {}
                url = fobj.get("url")
                name = payload.get("name") or (url or "").split("?")[0].split("/")[-1] or "attachment"
                if url:
                    out.append({"name": name, "url": url})
            if not page.get("has_more"):
                break
            cursor = page.get("next_cursor")
        return out

    # ---- 写回（提案制执行端；默认 dry_run，绝不未批先写） ----

    def create_row(self, data_source_id: str, props: dict[str, dict],
                   database_id: str | None = None, dry_run: bool = True) -> dict:
        """新建 tracker 行（Scout intake 批准后）。"""
        payload = {"parent": {"type": "data_source_id", "data_source_id": data_source_id},
                   "properties": {n: build_prop(s["type"], s["value"]) for n, s in props.items()}}
        if dry_run:
            return {"dry_run": True, "payload": payload}
        try:
            return self._request("POST", "/pages", payload)
        except NotionError:
            if not database_id:
                raise
            payload["parent"] = {"type": "database_id", "database_id": database_id}
            return self._request("POST", "/pages", payload, version=NOTION_VERSION_LEGACY)

    def update_page_properties(self, page_id: str, props: dict[str, dict],
                               dry_run: bool = True) -> dict:
        """props: {属性名: {"type": "status|select|rich_text|date|url|title", "value": ...}}"""
        payload = {"properties": {name: build_prop(spec["type"], spec["value"])
                                  for name, spec in props.items()}}
        if dry_run:
            return {"dry_run": True, "page_id": page_id, "payload": payload}
        return self._request("PATCH", f"/pages/{page_id}", payload)

    def archive_page(self, page_id: str) -> dict:
        """Notion 归档（非物理删除）——行从数据库消失，Notion 垃圾桶可恢复。"""
        return self._request("PATCH", f"/pages/{page_id}", {"archived": True})

    def append_body_markdown(self, page_id: str, markdown: str,
                             dry_run: bool = True, near_top: bool = True) -> dict:
        """正文条目写入（`### 日期` 倒序约定 → 尽量插在正文顶部附近）。"""
        children = markdown_to_blocks(markdown)
        payload: dict = {"children": children}
        if near_top and not dry_run:
            first = self._request("GET", f"/blocks/{page_id}/children?page_size=1")
            results = first.get("results", [])
            if results:
                payload["after"] = results[0]["id"]
        if dry_run:
            return {"dry_run": True, "page_id": page_id, "blocks": len(children)}
        return self._request("PATCH", f"/blocks/{page_id}/children", payload)


def _plain(rich: list[dict]) -> str:
    return "".join(part.get("plain_text", "") for part in rich)


def simplify_page(page: dict[str, Any]) -> dict[str, Any]:
    """Notion page 对象 → 扁平字典（字段名与 tracker schema 一致，见 models.Opportunity）。"""
    out: dict[str, Any] = {
        "notion_page_id": page.get("id"),
        "url": page.get("url"),
        "created": page.get("created_time"),
        "last_edited": page.get("last_edited_time"),
    }
    for name, prop in (page.get("properties") or {}).items():
        ptype = prop.get("type")
        val: Any = None
        if ptype == "title":
            val = _plain(prop["title"])
        elif ptype == "rich_text":
            val = _plain(prop["rich_text"]) or None
        elif ptype in ("select", "status"):
            val = (prop[ptype] or {}).get("name")
        elif ptype == "date":
            val = (prop["date"] or {}).get("start")
        elif ptype in ("url", "email", "phone_number", "number", "checkbox"):
            val = prop.get(ptype)
        elif ptype == "multi_select":
            val = [o["name"] for o in prop["multi_select"]] or None
        out[name] = val
    return out


def build_prop(ptype: str, value: Any) -> dict[str, Any]:
    """扁平值 → Notion 属性写入 payload。value=None 表示清空。"""
    if ptype in ("rich_text", "title"):
        return {ptype: [{"type": "text", "text": {"content": str(value)}}] if value else []}
    if ptype in ("select", "status"):
        return {ptype: {"name": str(value)} if value else None}
    if ptype == "date":
        return {"date": {"start": str(value)} if value else None}
    if ptype == "url":
        return {"url": value or None}
    raise ValueError(f"不支持的属性类型：{ptype}")


def markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    """极简 markdown → Notion blocks（### 标题 / - 列表 / 其余段落）。"""
    blocks: list[dict[str, Any]] = []
    for line in markdown.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            btype, text = "heading_3", line[4:]
        elif line.startswith("- "):
            btype, text = "bulleted_list_item", line[2:]
        else:
            btype, text = "paragraph", line
        blocks.append({"object": "block", "type": btype,
                       btype: {"rich_text": [{"type": "text", "text": {"content": text[:1900]}}]}})
    return blocks


def notion_configured(cfg) -> bool:
    """Notion 是否真的可用：token 与 tracker_data_source_id 都得有。

    调用方过去只看 token，而 config.example 里 token 是占位符 `ntn_xxx`（真值）、
    data_source_id 留空——照示例配置的新用户会被判成「已配 Notion」，
    于是 `joblander daily` / `pull` 与 daemon 晨报统统崩在 pull_tracker 里。"""
    n = cfg.raw.get("notion") or {}
    tok = str(n.get("token") or "").strip()
    return bool(tok) and not tok.startswith("ntn_xxx") and bool(n.get("tracker_data_source_id"))


def pull_tracker(cfg) -> list[dict[str, Any]]:
    """全量拉取 → 写投影 <workspace>/09-projections/tracker.json → 记 tracker.pulled 事件。"""
    from joblander.eventlog import EventLog

    ncfg = cfg.raw.get("notion", {})
    token, ds_id = ncfg.get("token"), ncfg.get("tracker_data_source_id")
    if not token or not ds_id:
        raise NotionError("config.notion 缺 token / tracker_data_source_id")

    client = NotionClient(token)
    rows = [simplify_page(p) for p in client.iter_rows(ds_id, ncfg.get("tracker_database_id"))]

    proj_dir = cfg.workspace_dir / "09-projections"
    proj_dir.mkdir(parents=True, exist_ok=True)
    proj_path = proj_dir / "tracker.json"
    with open(proj_path, "w", encoding="utf-8") as f:
        json.dump({"pulled_rows": len(rows), "rows": rows}, f, ensure_ascii=False, indent=1)

    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "tracker.pulled", "joblander.notion",
        {"rows": len(rows), "projection": str(proj_path)})
    return rows


DIFF_FIELDS = ("Status", "Priority", "Next Steps", "Highlight", "Follow-up Reminder",
               "Position", "Contact Person")


def diff_rows(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """两次投影对比 → 变更清单（F2：他直改 Notion 的动作要成为事件）。"""
    old_by_id = {r.get("notion_page_id"): r for r in old}
    changes: list[dict[str, Any]] = []
    for r in new:
        pid = r.get("notion_page_id")
        prev = old_by_id.get(pid)
        if prev is None:
            changes.append({"page_id": pid, "company": r.get("Company"), "kind": "row.added"})
            continue
        for f in DIFF_FIELDS:
            if (prev.get(f) or None) != (r.get(f) or None):
                changes.append({"page_id": pid, "company": r.get("Company"),
                                "kind": "field.changed", "field": f,
                                "old": prev.get(f), "new": r.get(f)})
    new_ids = {r.get("notion_page_id") for r in new}
    for pid, prev in old_by_id.items():
        if pid not in new_ids:
            changes.append({"page_id": pid, "company": prev.get("Company"),
                            "kind": "row.removed"})
    return changes


def pull_tracker_with_diff(cfg) -> list[dict[str, Any]]:
    """pull + diff：变更以 notion.edited 事件回流（系统自身写回 5 分钟内的变更不重复入账，
    以 row.edited / proposal.applied 事件近似去重——字段级 LWW，冲突即最后写者）。"""
    from joblander.eventlog import EventLog

    proj_path = cfg.workspace_dir / "09-projections" / "tracker.json"
    old: list[dict[str, Any]] = []
    if proj_path.exists():
        try:
            old = json.loads(proj_path.read_text(encoding="utf-8")).get("rows", [])
        except Exception:
            old = []
    rows = pull_tracker(cfg)
    changes = diff_rows(old, rows) if old else []
    if changes:
        log = EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl")
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone(timedelta(hours=8))) - timedelta(minutes=6)).isoformat()
        recent_own = {(e["payload"].get("page_id"), e["payload"].get("field"))
                      for e in log.events()
                      if e["ts"] >= cutoff and e["kind"] in ("row.edited",)}
        for c in changes:
            if (c.get("page_id"), c.get("field")) in recent_own:
                continue                      # 我们自己刚写的，不算他改的
            log.append("notion.edited", "human_via_notion", c)
    return rows


if __name__ == "__main__":
    from joblander.config import load_config

    rows = pull_tracker(load_config())
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.get("Status") or "?"] = by_status.get(r.get("Status") or "?", 0) + 1
    print(f"pulled {len(rows)} rows")
    for k, v in sorted(by_status.items()):
        print(f"  {k}: {v}")
