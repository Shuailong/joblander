"""提案执行（CLI 与 Web 共用）。dry_run 默认 True——未批准永不写。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIELD_TYPES = {"Status": "status", "Priority": "select", "Highlight": "rich_text",
               "Next Steps": "rich_text", "Follow-up Reminder": "date"}


def notion_write_enabled(cfg) -> bool:
    """Notion 退役开关（UI v2 / ADR-14）：false = 本地档案是唯一写入面，Notion 变只读镜像。
    没配 token 一律视为关闭——Notion 是可选集成，没凭证就谈不上「写得成」。"""
    n = cfg.raw.get("notion") or {}
    return bool(n.get("token")) and bool(n.get("write_enabled", True))


def _patch_projection(cfg, page_id: str, fields: dict[str, Any]) -> None:
    """写后即时更新本地投影——UI 不等下一次全量 pull；Notion 关写后这就是唯一投影更新路径。"""
    proj = cfg.workspace_dir / "09-projections" / "tracker.json"
    if not proj.exists() or not page_id:
        return
    data = json.loads(proj.read_text(encoding="utf-8"))
    for r in data["rows"]:
        if (r.get("notion_page_id") or "").replace("-", "") == page_id.replace("-", ""):
            for k, v in fields.items():
                r[k] = v if v != "" else None
    proj.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _append_projection(cfg, page: dict[str, Any]) -> None:
    """入池新建行立即进投影——否则作战室要等下一轮全量 pull（约 15 分钟）才看得到，
    「刚入池的机会怎么不见了」（2026-08-10 用户报障）。幂等：同 page_id 已在则跳过。"""
    proj = cfg.workspace_dir / "09-projections" / "tracker.json"
    if not proj.exists() or not page.get("id"):
        return
    from joblander.notion import simplify_page
    try:
        row = simplify_page(page)
    except Exception:
        return
    data = json.loads(proj.read_text(encoding="utf-8"))
    pid = (row.get("notion_page_id") or "").replace("-", "")
    if any((r.get("notion_page_id") or "").replace("-", "") == pid
           for r in data["rows"]):
        return
    data["rows"].append(row)
    data["pulled_rows"] = len(data["rows"])
    proj.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def list_pending(cfg) -> list[dict[str, Any]]:
    out = []
    for d in ("11-shadow", "12-intake"):
        base = cfg.workspace_dir / d
        if not base.exists():
            continue
        for f in sorted(base.glob("*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("approved") is None:
                data["_file"] = str(f)
                data["_dir"] = d
                from datetime import datetime, timedelta, timezone
                data["_created"] = datetime.fromtimestamp(
                    f.stat().st_mtime, timezone(timedelta(hours=8))
                ).strftime("%m-%d %H:%M")
                out.append(data)
    return out


def _proposal_file(cfg, proposal_path: str | Path) -> Path:
    """提案路径必须落在 workspace 的提案目录内。

    这两个参数直接来自 web 表单（/api/proposal/apply|reject|amend_apply）。
    不夹紧的话，reject 会把任意 JSON 文件改写成带 approved:false 的内容，
    apply 还能顺着 jd_file 删掉 workspace 外的文件。"""
    p = Path(proposal_path).expanduser().resolve()
    allowed = [(cfg.workspace_dir / d).resolve() for d in ("11-shadow", "12-intake")]
    if not any(p == a or a in p.parents for a in allowed):
        raise ValueError(f"提案路径越界：{p}（只允许 11-shadow / 12-intake 下的文件）")
    if not p.is_file():
        raise ValueError(f"提案不存在：{p}")
    return p


def _ws_file(cfg, rel: str) -> Path | None:
    """提案里记的 workspace 相对路径 → 绝对路径；越界或不存在返回 None。
    `workspace_dir / "/etc/passwd"` 在 pathlib 里等于 `/etc/passwd`——绝对路径与
    `..` 都能逃出 workspace，而这个值下游是要被 unlink 的。"""
    if not rel:
        return None
    p = (cfg.workspace_dir / rel).resolve()
    ws = cfg.workspace_dir.resolve()
    if ws not in p.parents or not p.is_file():
        return None
    return p


def apply_proposal(cfg, proposal_path: str | Path, yes: bool = False) -> dict[str, Any]:
    from joblander.eventlog import EventLog
    from joblander.notion import NotionClient

    pf = _proposal_file(cfg, proposal_path)
    proposal = json.loads(pf.read_text(encoding="utf-8"))
    nwrite_cfg = cfg.raw.get("notion") or {}
    # Notion 是可选集成（README/config.example）：没配就不建 client，
    # 此前无条件取 cfg.raw["notion"] 让纯本地用户一批准提案就 KeyError——
    # 提案制是整个系统的核心闸门，等于核心功能对他们完全不可用。
    client = NotionClient(nwrite_cfg["token"]) if nwrite_cfg.get("token") else None
    dry = not yes
    nwrite = notion_write_enabled(cfg)
    result: dict[str, Any] = {"dry_run": dry, "file": pf.name}
    if not nwrite:
        result["notion"] = "skipped（write_enabled=false，只写本地档案）"

    if "field_diffs" in proposal:                      # Scribe 提案
        props = {k: {"type": FIELD_TYPES[k], "value": v}
                 for k, v in (proposal.get("field_diffs") or {}).items() if k in FIELD_TYPES}
        if nwrite:
            # 字段照写（Tracker 状态是共享事实）；正文条目只入本地时间线——
            # 2026-08-10 起公司页不做内容同步，Notion 上看历史走页面链接
            result["properties"] = client.update_page_properties(
                proposal["notion_page_id"], props, dry_run=dry)
        if not dry:
            _patch_projection(cfg, proposal.get("notion_page_id") or "",
                              proposal.get("field_diffs") or {})
            if proposal.get("body_entry"):              # 档案时间线：批准即入档
                from joblander import company as companyfile
                src = "scout" if str(proposal.get("origin", "")).startswith("scout") \
                    else "scribe"
                entry = companyfile.add_from_markdown(
                    cfg, proposal.get("company") or "", proposal["body_entry"],
                    author="ai", source=src, ref=pf.name,
                    attachments=proposal.get("attachments") or [])
                result["timeline"] = entry["id"]
            if proposal.get("playbook_updates"):        # F3：批准即回写战况
                from joblander.playbook import apply_updates
                result["playbook"] = apply_updates(
                    cfg, proposal["playbook_updates"], company=proposal.get("company", ""))
    elif proposal.get("kind") == "calendar.event":     # 排期缺口 → 建日历事件
        if not dry:
            date, tm = proposal.get("date") or "", proposal.get("time") or ""
            if not (date and tm):
                raise ValueError("需要日期与时间——先在卡片上补齐再确认")
            from datetime import datetime as _dt, timedelta as _td
            start = _dt.fromisoformat(f"{date}T{tm}:00+08:00")
            end = start + _td(minutes=int(proposal.get("duration_min") or 60))
            from joblander import calendar_sync
            # UI 上的「确认建事件」= ADR-10 要求的逐次人工确认（详情就摆在卡片上）
            result["calendar"] = calendar_sync.create_event(
                cfg, proposal.get("title") or "面试", start.isoformat(), end.isoformat(),
                description=f"joblander · {proposal.get('company') or ''}", confirmed=True)
    elif proposal.get("kind") == "diary.entry":        # 晚间日记 → 参谋部日报「今日日记」段
        if not dry:
            from datetime import datetime, timedelta, timezone

            from joblander.daily import DIARY_HEADER, daily_path, upsert_section
            date = proposal.get("date") or datetime.now(
                timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
            out = upsert_section(daily_path(cfg, date), DIARY_HEADER,
                                 proposal["body_entry"], title=f"# 日报 · {date}")
            result["diary"] = str(out)
        # Notion 找工日记只作镜像，退役开关关掉即停
        if nwrite and proposal.get("notion_page_id"):
            result["diary_notion"] = client.append_body_markdown(
                proposal["notion_page_id"], proposal["body_entry"],
                dry_run=dry, near_top=False)
    elif proposal.get("kind") == "lead.intake":        # Scout 提案
        lead = proposal["lead"]
        props = {"Company": {"type": "title", "value": lead.get("company") or "（未披露）"},
                 "Position": {"type": "rich_text", "value": lead.get("position")},
                 "Status": {"type": "status", "value": "Added"},
                 "Priority": {"type": "select", "value": "Low"},
                 "Highlight": {"type": "rich_text", "value": lead.get("highlight")},
                 "Next Steps": {"type": "rich_text", "value": lead.get("suggested_next_step")}}
        if lead.get("urls"):                        # 链接入池 → Job URL 落行（JD 挖掘直接可用）
            props["Job URL"] = {"type": "url", "value": lead["urls"][0]}
        if nwrite:
            result["create"] = client.create_row(
                nwrite_cfg["tracker_data_source_id"], props,
                nwrite_cfg.get("tracker_database_id"),
                dry_run=dry)
            if not dry:
                _append_projection(cfg, result["create"])
        if not dry and lead.get("company"):             # 档案：入池即建档
            from joblander import company as companyfile
            companyfile.timeline_add(
                cfg, lead["company"], kind="intake", title="入池",
                summary=lead.get("highlight") or "",
                content_md=f"- 岗位：{lead.get('position') or '—'}\n"
                           f"- 渠道：{proposal.get('source_hint') or '—'}\n"
                           + (f"- 📊 {lead['market_ref']}\n" if lead.get("market_ref") else "")
                           + f"- 建议动作：{lead.get('suggested_next_step') or '—'}",
                author="ai", source="intake", ref=pf.name)
            if lead.get("jd_excerpt"):                  # JD 随入池落档 → 公司页评估直接有料
                companyfile.save_upload(
                    cfg, lead["company"],
                    f"jd-{proposal.get('source_hint') or 'intake'}.txt",
                    lead["jd_excerpt"].encode("utf-8"), kind="jd")
            if proposal.get("jd_file"):                 # 录入时上传的 JD 附件随批准落档
                src = _ws_file(cfg, proposal["jd_file"])
                if src is not None:
                    companyfile.save_upload(
                        cfg, lead["company"],
                        src.name.split("-", 1)[-1] or src.name,
                        src.read_bytes(), kind="jd")
                    src.unlink()
            try:                                        # W14：入池即跑内推匹配——失败不阻塞入库
                from joblander.llm import from_config
                from joblander.referral import format_referral_md, suggest_referral
                ref = suggest_referral(cfg, from_config(cfg, "flash"), lead["company"])
                if not ref.get("error"):
                    companyfile.timeline_add(
                        cfg, lead["company"], kind="note",
                        title="内推匹配（W14 · 入池自动）",
                        summary=f"{len(ref.get('matches') or [])} 位候选",
                        content_md=format_referral_md(ref),
                        author="ai", source="referral", ref=pf.name)
                    result["referral_matches"] = len(ref.get("matches") or [])
            except Exception as e:
                EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
                    "referral.failed", "joblander.applyops",
                    {"company": lead.get("company"), "error": str(e)[:200]})
    else:
        raise ValueError(f"未知提案类型：{pf.name}")

    if not dry:
        proposal["approved"] = True
        pf.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding="utf-8")
        EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
            "proposal.applied", "human_approved", {"file": pf.name})
    return result


def amend_proposal(cfg, proposal_path: str | Path,
                   new_fields: dict[str, Any]) -> dict[str, Any]:
    """改后批的「改」：更新提案内容（field_diffs / lead 字段），并记录人工修正。"""
    pf = _proposal_file(cfg, proposal_path)
    proposal = json.loads(pf.read_text(encoding="utf-8"))
    edited = []
    if "field_diffs" in proposal:
        for k, v in new_fields.items():
            if k in FIELD_TYPES:
                if v == "":
                    v = None
                if proposal["field_diffs"].get(k) != v:
                    proposal["field_diffs"][k] = v
                    edited.append(k)
    elif proposal.get("kind") == "calendar.event":
        for k in ("title", "date", "time", "duration_min"):
            if k in new_fields and proposal.get(k) != new_fields[k]:
                proposal[k] = new_fields[k]
                edited.append(k)
    elif proposal.get("kind") == "diary.entry":
        if "body_entry" in new_fields and proposal.get("body_entry") != new_fields["body_entry"]:
            proposal["body_entry"] = new_fields["body_entry"]
            edited.append("body_entry")
    elif proposal.get("kind") == "lead.intake":
        for k in ("company", "position", "highlight", "suggested_next_step"):
            if k in new_fields and proposal["lead"].get(k) != new_fields[k]:
                proposal["lead"][k] = new_fields[k]
                edited.append(k)
    if edited:
        proposal.setdefault("human_edits", []).extend(edited)
        pf.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"edited": edited}


ROW_EDITABLE = {"Status": "status", "Priority": "select", "Next Steps": "rich_text",
                "Highlight": "rich_text", "Follow-up Reminder": "date",
                "Contact Person": "rich_text", "Position": "rich_text",
                "Date Applied": "date", "Job URL": "url", "Company": "title"}


def update_row_field(cfg, page_id: str, field: str, value: Any) -> dict[str, Any]:
    """人工在 UI 上直改一格 = 已批准的写（等价于他直接改 Notion）。"""
    from joblander.eventlog import EventLog
    from joblander.notion import NotionClient

    if field not in ROW_EDITABLE:
        raise ValueError(f"字段不可编辑：{field}")
    if value == "":
        value = None
    if field == "Company":
        if not value:
            raise ValueError("公司名不能清空")
        old_name = _row_company(cfg, page_id)
    notion_written = False
    if notion_write_enabled(cfg):
        client = NotionClient(cfg.raw["notion"]["token"])
        result = client.update_page_properties(
            page_id, {field: {"type": ROW_EDITABLE[field], "value": value}}, dry_run=False)
        notion_written = bool(result)
    _patch_projection(cfg, page_id, {field: value})
    if field == "Company" and old_name and old_name != value:
        from joblander.company import rename_company
        rename_company(cfg, old_name, value)
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "row.edited", "human_direct", {"page_id": page_id, "field": field,
                                       "value": value})
    return {"ok": True, "field": field, "value": value, "notion": notion_written}


def _row_company(cfg, page_id: str) -> str | None:
    proj = cfg.workspace_dir / "09-projections" / "tracker.json"
    if not proj.exists() or not page_id:
        return None
    data = json.loads(proj.read_text(encoding="utf-8"))
    for r in data["rows"]:
        if (r.get("notion_page_id") or "").replace("-", "") == page_id.replace("-", ""):
            return r.get("Company")
    return None


def archive_row(cfg, page_id: str) -> dict[str, Any]:
    """删除一行（人工 UI 动作）：Notion 归档（垃圾桶可恢复）+ 投影移除。
    本地公司档案（18-companies）保留——删的是战线条目，不是历史。"""
    from joblander.eventlog import EventLog
    from joblander.notion import NotionClient

    proj = cfg.workspace_dir / "09-projections" / "tracker.json"
    company = ""
    if proj.exists():
        data = json.loads(proj.read_text(encoding="utf-8"))
        keep = []
        for r in data["rows"]:
            if (r.get("notion_page_id") or "").replace("-", "") == page_id.replace("-", ""):
                company = r.get("Company") or ""
            else:
                keep.append(r)
        if not company:
            raise ValueError("行不存在")
        data["rows"] = keep
        proj.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    notion_written = False
    if notion_write_enabled(cfg):
        NotionClient(cfg.raw["notion"]["token"]).archive_page(page_id)
        notion_written = True
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "row.archived", "human_direct",
        {"page_id": page_id, "company": company, "notion": notion_written})
    return {"ok": True, "company": company, "notion": notion_written}


def reject_proposal(cfg, proposal_path: str | Path, reason: str = "") -> dict[str, Any]:
    from joblander.eventlog import EventLog

    pf = _proposal_file(cfg, proposal_path)
    proposal = json.loads(pf.read_text(encoding="utf-8"))
    proposal["approved"] = False
    if reason:
        proposal["reject_reason"] = reason
    pf.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding="utf-8")
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "proposal.rejected", "human", {"file": pf.name, "reason": reason})
    return {"rejected": pf.name}
