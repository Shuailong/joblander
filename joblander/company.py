"""公司档案（Company File）— 每家公司的本地事实源：结构化卡片 + 战役时间线 + 附件（UI v2 / ADR-14）。

三层数据，一个目录（<workspace>/18-companies/<slug>/）：
- meta.json       投递信息（入库、简历版本、岗位亮点）+ 匹配评估快照（W2）
- timeline.jsonl  战役时间线：面试/电话/邮件/笔记/复盘，author 分明（ai | human）
- jd/ attachments/  JD 原文与附件（PDF 纪要、贴入材料落盘）

Notion 退役路径：Notion 正文只是「存量镜像 + 移动端入口」。时间线合并两路——本地条目 +
Notion 正文 `### YYYY-MM-DD` 存量条目，按（日期,标题）去重、本地优先；给存量条目补人工复盘
会把它「本地化」。存量随日常使用自然迁走，不需要一次性搬家。
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SGT = timezone(timedelta(hours=8))

KINDS = ("interview", "oa", "call", "email", "apply", "note", "retro", "assessment",
         "intake", "transcript")
KIND_LABELS = {"interview": "面试", "oa": "笔试", "call": "通话", "email": "邮件",
               "apply": "投递", "note": "笔记", "retro": "复盘", "assessment": "评估",
               "intake": "入池", "transcript": "转写"}
# 实战记录（有对手、有复盘价值）：能力画像证据、周报战况、附件优先绑定都认这一档
BATTLE_KINDS = ("interview", "oa", "call", "transcript")


def slugify(company: str) -> str:
    return (company or "unknown").split("（")[0].split("(")[0].strip() \
        .replace(" ", "-").replace("/", "-")[:60] or "unknown"


def company_dir(cfg, company: str, create: bool = False) -> Path:
    d = cfg.workspace_dir / "18-companies" / slugify(company)
    if create:
        (d / "jd").mkdir(parents=True, exist_ok=True)
        (d / "attachments").mkdir(parents=True, exist_ok=True)
    return d


def _log(cfg):
    from joblander.eventlog import EventLog
    return EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl")


def rename_company(cfg, old_name: str, new_name: str) -> None:
    """公司改名：本地档案（18-companies 目录 + 尽调档案）跟着搬家，保持时间线/附件/
    简历版本连续——这些全挂在 company_dir 下，目录一搬全带走。目标 slug 已有档案
    （撞名/合并）时拒绝，不悄悄覆盖或合并成一家。10-briefs 里旧文件名不追溯改，
    历史快照，不影响功能（build_brief 之后按新名字出新文件）。"""
    old_slug, new_slug = slugify(old_name), slugify(new_name)
    if old_slug == new_slug:
        return
    old_dir = cfg.workspace_dir / "18-companies" / old_slug
    new_dir = cfg.workspace_dir / "18-companies" / new_slug
    if old_dir.exists():
        if new_dir.exists():
            raise ValueError(f"改名冲突：「{new_name}」（{new_slug}）本地已有档案，先处理重名")
        old_dir.rename(new_dir)
    old_dossier = cfg.workspace_dir / "14-dossiers" / f"{old_slug}.json"
    new_dossier = cfg.workspace_dir / "14-dossiers" / f"{new_slug}.json"
    if old_dossier.exists() and not new_dossier.exists():
        old_dossier.rename(new_dossier)
    _log(cfg).append("company.renamed", "human_direct", {"old": old_name, "new": new_name})


# ---------- meta：投递信息 + 匹配评估 ----------

def load_meta(cfg, company: str) -> dict[str, Any]:
    p = company_dir(cfg, company) / "meta.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_meta(cfg, company: str, patch: dict[str, Any]) -> dict[str, Any]:
    meta = load_meta(cfg, company)
    meta.update({k: v for k, v in patch.items()})
    meta["updated"] = datetime.now(SGT).isoformat(timespec="seconds")
    d = company_dir(cfg, company, create=True)
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    _log(cfg).append("company.meta_updated", "human_direct",
                     {"company": company, "fields": sorted(patch.keys())})
    return meta


def intake_date(cfg, row: dict[str, Any]) -> str | None:
    """入库时间：人工覆盖 > Notion 行创建时间 > 时间线最早条目。"""
    meta = load_meta(cfg, row.get("Company") or "")
    if meta.get("intake_date"):
        return meta["intake_date"]
    if row.get("created"):
        return str(row["created"])[:10]
    entries = local_entries(cfg, row.get("Company") or "")
    dates = sorted(e["date"] for e in entries if e.get("date"))
    return dates[0] if dates else None


# ---------- 时间线 ----------

def local_entries(cfg, company: str) -> list[dict[str, Any]]:
    p = company_dir(cfg, company) / "timeline.jsonl"
    out: list[dict[str, Any]] = []
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _write_all(cfg, company: str, entries: list[dict[str, Any]]) -> None:
    d = company_dir(cfg, company, create=True)
    text = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)
    (d / "timeline.jsonl").write_text(text, encoding="utf-8")


def timeline_add(cfg, company: str, *, kind: str = "note", title: str = "",
                 date: str | None = None, content_md: str = "", summary: str = "",
                 participants: list[str] | None = None,
                 attachments: list[str] | None = None,
                 author: str = "human", source: str = "manual",
                 ref: str = "") -> dict[str, Any]:
    now = datetime.now(SGT)
    entry = {
        "id": f"tl-{now.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2)}",
        # ts 微秒级：批量落库（backfill）同秒多条也保得住先后，展示排序全靠它
        "ts": now.isoformat(timespec="microseconds"),
        "date": (date or now.strftime("%Y-%m-%d"))[:10],
        "kind": kind if kind in KINDS else "note",
        "title": title.strip() or KIND_LABELS.get(kind, "记录"),
        "participants": participants or [],
        "summary": summary,
        "content_md": content_md,
        "attachments": attachments or [],
        "author": author,           # ai | human —— UI 上必须可分辨（UI v2 铁律）
        "source": source,           # scribe | manual | assess | intake | upload …
    }
    if ref:
        entry["ref"] = ref
    entries = local_entries(cfg, company)
    entries.append(entry)
    _write_all(cfg, company, entries)
    # 事件带作战日期（payload.date）：录入时间是 ts，仗打的日子是 date——统计一律按 date
    _log(cfg).append("company.timeline_added", f"{author}:{source}",
                     {"company": company, "kind": entry["kind"], "title": entry["title"],
                      "date": entry["date"], "id": entry["id"]})
    return entry


def timeline_upsert(cfg, company: str, *, title_prefix: str | tuple[str, ...],
                    source: str, kind: str = "note", title: str = "", summary: str = "",
                    content_md: str = "") -> dict[str, Any]:
    """AI 周期性产物的去重落档：同 source+标题前缀的条目就地更新，否则新增。
    prefix 可传元组——产物改名时把旧前缀一并列入，老条目就地换新名而不是堆重复。"""
    olds = [e for e in local_entries(cfg, company)
            if e.get("source") == source
            and (e.get("title") or "").startswith(title_prefix)]
    if olds:
        now = datetime.now(SGT)
        return update_entry(cfg, company, olds[-1]["id"], {
            "date": now.strftime("%Y-%m-%d"),
            "ts": now.isoformat(timespec="microseconds"),
            "title": title or olds[-1]["title"], "summary": summary,
            "content_md": content_md})
    fallback = title_prefix if isinstance(title_prefix, str) else title_prefix[0]
    return timeline_add(cfg, company, kind=kind, title=title or fallback,
                        summary=summary, content_md=content_md,
                        author="ai", source=source)


def update_entry(cfg, company: str, entry_id: str,
                 patch: dict[str, Any]) -> dict[str, Any] | None:
    entries = local_entries(cfg, company)
    hit = None
    for e in entries:
        if e.get("id") == entry_id:
            e.update(patch)
            hit = e
            break
    if hit is not None:
        _write_all(cfg, company, entries)
    return hit


def detach_attachment(cfg, company: str, entry_id: str, rel: str) -> dict[str, Any]:
    """把附件从事件上移除——文件不销毁（留在 attachments/ 作未绑附件，可手动重挂），
    并记入 detached_atts 防自动绑回。"""
    entries = local_entries(cfg, company)
    hit = next((e for e in entries if e.get("id") == entry_id), None)
    if hit is None:
        raise ValueError("条目不存在")
    atts = hit.get("attachments") or []
    if rel not in atts:
        raise ValueError("该附件不在这条事件上")
    hit["attachments"] = [a for a in atts if a != rel]
    if rel not in hit.setdefault("detached_atts", []):
        hit["detached_atts"].append(rel)
    _write_all(cfg, company, entries)
    _log(cfg).append("company.attachment_detached", "human_direct",
                     {"company": company, "entry": entry_id, "file": rel})
    return hit


def delete_entry(cfg, company: str, *, entry_id: str = "", date: str = "",
                 title: str = "") -> dict[str, Any]:
    """删除时间线条目。本地条目物理删除；(date,title) 记墓碑防 Notion 合并流带回。
    附件文件不销毁（留在 attachments/ 可重挂），但记入 meta.unbound_atts——
    否则绑回器把游离附件重建成事件，人删几次就被顶回几次（2026-08-11 报障）。"""
    entries = local_entries(cfg, company)
    hit = next((e for e in entries if entry_id and e.get("id") == entry_id), None)
    if hit is not None:
        entries = [e for e in entries if e.get("id") != entry_id]
        _write_all(cfg, company, entries)
        date, title = hit.get("date") or date, hit.get("title") or title
        atts = hit.get("attachments") or []
        if atts:
            cur = load_meta(cfg, company).get("unbound_atts") or []
            fresh = [a for a in atts if a not in cur]
            if fresh:
                save_meta(cfg, company, {"unbound_atts": cur + fresh})
    elif not (date and title):
        raise ValueError("条目不存在（Notion 存量条目需带 date+title）")
    _add_tombstone(cfg, company, date, title)
    _log(cfg).append("company.entry_deleted", "human_direct",
                     {"company": company, "id": entry_id or "(notion)",
                      "date": date, "title": title[:60]})
    return {"deleted": True, "date": date, "title": title}


def _add_tombstone(cfg, company: str, date: str, title: str) -> None:
    """(date,title) 记墓碑：Notion 合并流不再带回该键。删除与改名共用。"""
    keys = load_meta(cfg, company).get("deleted_keys") or []
    key = [date, _norm_title(title)]
    if key not in keys:
        keys.append(key)
        save_meta(cfg, company, {"deleted_keys": keys})


EDITABLE_ENTRY_FIELDS = {"kind", "date", "title", "participants", "summary", "content_md"}


def edit_entry(cfg, company: str, *, entry_id: str = "", date: str = "",
               title: str = "", fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """人工改事件（本地条目直接改；Notion 存量条目物化后改——带原文防丢，同 set_review）。
    人工动作不排队，改即生效；human_edited 时间戳留痕。
    改了日期/标题的，旧 (date,title) 记墓碑——否则 Notion 同键存量失去去重配对，
    合并流会把原条目再带回来，页面上看起来就是「保存变成了新建」。"""
    fields = fields or {}
    patch = {k: v for k, v in fields.items() if k in EDITABLE_ENTRY_FIELDS}
    if not patch:
        raise ValueError("没有可改的字段")
    if "kind" in patch and patch["kind"] not in KINDS:
        raise ValueError(f"未知类型：{patch['kind']}")
    if "date" in patch:
        patch["date"] = str(patch["date"])[:10]
    patch["human_edited"] = datetime.now(SGT).isoformat(timespec="seconds")
    if entry_id:
        cur = next((e for e in local_entries(cfg, company)
                    if e.get("id") == entry_id), None)
        hit = update_entry(cfg, company, entry_id, patch)
        if hit is not None:
            old_key = ((cur or {}).get("date"), _norm_title((cur or {}).get("title") or ""))
            if cur and old_key != (hit.get("date"), _norm_title(hit.get("title") or "")):
                _add_tombstone(cfg, company, cur.get("date") or "", cur.get("title") or "")
            _log(cfg).append("company.entry_edited", "human_direct",
                             {"company": company, "entry": entry_id,
                              "fields": sorted(k for k in patch if k != "human_edited")})
            return hit
    entry = timeline_add(
        cfg, company,
        kind=patch.get("kind") or guess_kind(title, fields.get("content_md", "")),
        title=patch.get("title") or title or "记录",
        date=patch.get("date") or date or None,
        content_md=fields.get("content_md", ""), summary=fields.get("summary", ""),
        participants=patch.get("participants") or [],
        author="human", source="manual")
    if date and title and \
       (date, _norm_title(title)) != (entry["date"], _norm_title(entry["title"])):
        _add_tombstone(cfg, company, date, title)
    return update_entry(cfg, company, entry["id"],
                        {"human_edited": patch["human_edited"]}) or entry


def set_review(cfg, company: str, *, entry_id: str = "", date: str = "",
               title: str = "", text: str = "", content_md: str = "",
               kind: str = "") -> dict[str, Any]:
    """「我的复盘」——人写的判断，挂在事件上，与 AI 内容分开存放与展示。
    对 Notion 存量条目（无本地记录）：物化成本地条目再挂——必须把原文与类型一并带入，
    否则合并去重后本地空壳胜出、纪要正文会从页面消失（2026-08-08 review 抓出的丢数据路径）。"""
    review = {"text": text, "updated": datetime.now(SGT).isoformat(timespec="seconds")}
    if entry_id:
        hit = update_entry(cfg, company, entry_id, {"my_review": review})
        if hit is not None:
            _log(cfg).append("company.review_written", "human_direct",
                             {"company": company, "entry": entry_id})
            return hit
    entry = timeline_add(cfg, company,
                         kind=kind or guess_kind(title, content_md),
                         title=title or "复盘", date=date or None,
                         content_md=content_md,
                         author="human", source="manual")
    return update_entry(cfg, company, entry["id"], {"my_review": review}) or entry


def _looks_interview(title: str) -> bool:
    return bool(re.search(r"面试|interview|onsite|loop|R\d|一面|二面|三面|终面|电面|技术面|HM ?面",
                          title or "", re.IGNORECASE))


_OA_PAT = (r"笔试|在线测评|online assessment|\bOA\b|take.?home|hackerrank|"
           r"codility|codesignal")


def guess_kind(title: str, content: str = "") -> str:
    """条目类型判定：标题 + 正文前 300 字一起看——他的记录习惯是「### 日期 人名」，
    标题常常只有人名（'Alex 2PM'），面试/通话的信号全在正文里（2026-08-08 教训）。"""
    t = title or ""
    if re.search(_OA_PAT, t, re.IGNORECASE):
        return "oa"
    if _looks_interview(t):
        return "interview"
    # 投递只认标题——正文里「已投递」常是进展叙述的一句，按标题才稳
    if re.search(r"已投|投递|applied|submitt", t, re.IGNORECASE):
        return "apply"
    probe = (t + " " + (content or "")[:300])
    if re.search(r"HR ?面|猎头|recruiter|screening|初筛|电话|call|聊了|沟通|catch.?up|"
                 r"通话|约了|meet(ing)?|zoom|face ?time|智能纪要", probe, re.IGNORECASE):
        return "call"    # 智能纪要=豆包通话/面试录音产物，默认按通话计
    if _looks_interview(probe):
        return "interview"
    if re.search(_OA_PAT, probe, re.IGNORECASE):
        return "oa"
    if re.search(r"邮件|email|inmail|回信", t, re.IGNORECASE):
        return "email"
    return "note"


CLASSIFY_SYSTEM = """你是求职作战档案的分类员。输入一批战报条目（标题+正文摘录），判定每条的类型：
- interview：正式面试环节（技术面、HM 面、HR 面试、onsite）
- oa：笔试/在线测评/take-home 作业（HackerRank、Codility、限时题、带回家项目）
- call：非正式对话——HR/猎头初聊、内推人沟通、朋友情报通话、WhatsApp 往来
- email：邮件往来记录
- apply：投递动作记录（申请已提交、投递渠道与版本）
- note：非对话记录——情报整理、准备材料、决策记录、入池登记、复盘摘要
输出严格 JSON：{"kinds": [{"i": 输入条目的 i, "kind": "interview|oa|call|email|apply|note"}, ...]}——
必须带回每条的 i（防错位），全部条目都要有。
纪律：看内容实质不看措辞；「准备/应对/评估某场面试」的材料是 note 不是 interview；
只发生在邮件里的往来是 email，真打了电话/视频/语音的才是 call。
特别注意：条目开头若是零散事实速记（band 数字、团队人数、bonus、HM 人名）——那是通话笔记，
即使后面粘贴了邮件或 JD 原文，整条也算 call。"""


def classify_entries(llm, items: list[dict[str, Any]]) -> list[str]:
    """LLM 批量判类型（关键词分类的兜底——他的标题常常只有人名，2026-08-08 教训）。"""
    if not items:
        return []
    payload = [{"i": i, "title": it.get("title", ""),
                "content": (it.get("content_md") or "")[:400]}
               for i, it in enumerate(items)]
    from joblander.scribe import _strip_fences
    raw = llm.generate(json.dumps(payload, ensure_ascii=False),
                       system=CLASSIFY_SYSTEM, json_mode=True)
    got = json.loads(_strip_fences(raw)).get("kinds") or []
    valid = {"interview", "oa", "call", "email", "apply", "note"}
    by_i: dict[int, str] = {}
    for k in got:
        if isinstance(k, dict) and k.get("kind") in valid:
            by_i[int(k.get("i", -1))] = k["kind"]
    # 兼容裸数组返回；缺失的保持原 kind（宁不改不错改）
    if not by_i and got and isinstance(got[0], str):
        by_i = {i: k for i, k in enumerate(got) if k in valid}
    return [by_i.get(i, items[i].get("kind") or "note") for i in range(len(items))]


ENTRY_HEAD = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2})\s*(.*)$")


def parse_notion_entries(body_text: str) -> list[dict[str, Any]]:
    """Notion 正文 → 存量条目（约定：`### YYYY-MM-DD 事件/人名` 分段，倒序全史）。"""
    out: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    buf: list[str] = []
    def _close(c: dict, lines: list[str]) -> None:
        c["content_md"] = "\n".join(lines).strip()
        c["kind"] = guess_kind(c["title"], c["content_md"])   # 正文到齐才能判类型
        out.append(c)

    for line in (body_text or "").splitlines():
        m = ENTRY_HEAD.match(line.strip())
        if m:
            if cur is not None:
                _close(cur, buf)
            cur = {"date": m.group(1), "title": m.group(2).strip() or "记录",
                   "author": "human", "source": "notion",
                   "participants": [], "attachments": []}
            buf = []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        _close(cur, buf)
    return out


def _norm_title(t: str) -> str:
    return re.sub(r"\s+", "", (t or "").casefold())


def merged_timeline(cfg, company: str, notion_body: str = "") -> list[dict[str, Any]]:
    """本地 + Notion 存量合并，（日期,标题）去重、本地优先。倒序（新在上）。"""
    local = local_entries(cfg, company)
    tombs = {tuple(k) for k in (load_meta(cfg, company).get("deleted_keys") or [])}
    seen = {(e.get("date"), _norm_title(e.get("title"))) for e in local}
    merged = list(local)
    for e in parse_notion_entries(notion_body):
        key = (e["date"], _norm_title(e["title"]))
        if key in tombs:
            continue
        if key in seen:
            for l in merged:
                if (l.get("date"), _norm_title(l.get("title"))) == key:
                    l["also_in_notion"] = True
            continue
        merged.append(e)
    return sorted(merged, key=lambda e: (e.get("date") or "", e.get("ts") or ""),
                  reverse=True)


def add_from_markdown(cfg, company: str, body_entry: str, *, author: str = "ai",
                      source: str = "scribe", ref: str = "",
                      attachments: list[str] | None = None) -> dict[str, Any]:
    """Scribe 的 body_entry（### 日期 标题 开头）→ 时间线条目。批准提案时自动调用。"""
    first = next((l for l in body_entry.splitlines() if l.strip()), "")
    m = ENTRY_HEAD.match(first.strip())
    date = m.group(1) if m else None
    title = (m.group(2).strip() if m else "") or "面后录入"
    return timeline_add(cfg, company, kind=guess_kind(title, body_entry), title=title, date=date,
                        content_md=body_entry, author=author, source=source, ref=ref,
                        attachments=attachments or [])


def backfill_from_notion(cfg, notion_client, rows: list[dict[str, Any]],
                         active_only: bool = False, llm=None) -> dict[str, int]:
    """历史回溯：Notion 正文的 `### 日期` 存量条目 → 本地时间线 + 事件入库。

    诚实入账（ADR-13 补充）：事件 ts=回溯执行时刻，作战日期在 payload.date——
    不伪造历史时间戳，统计一律按 payload.date。幂等：(日期,标题) 已有本地条目则跳过；
    已删/已改名的键（deleted_keys 墓碑）不回填。
    落库按正文倒序（旧的先入）：ts 随之递增，展示排序后同日条目仍是正文原顺序。"""
    ACTIVE_STATUSES = {"Added", "Dream", "In Consideration", "To Apply", "Screening Called",
                       "Applied", "Interview Scheduled", "Interview Completed"}
    added = skipped = failed = 0
    ambiguous: list[tuple[str, dict]] = []      # (company, entry)：关键词判成 note 的交 LLM 终审
    for row in rows:
        if active_only and row.get("Status") not in ACTIVE_STATUSES:
            continue
        name = row.get("Company") or ""
        if not name or not row.get("notion_page_id"):
            continue
        try:
            body = cached_body(cfg, notion_client, row, force=True)
        except Exception:
            failed += 1
            continue
        have = {(e.get("date"), _norm_title(e.get("title")))
                for e in local_entries(cfg, name)}
        have |= {tuple(k) for k in (load_meta(cfg, name).get("deleted_keys") or [])}
        for e in reversed(parse_notion_entries(body)):
            key = (e["date"], _norm_title(e["title"]))
            if key in have:
                skipped += 1
                continue
            saved = timeline_add(cfg, name, kind=e["kind"], title=e["title"],
                                 date=e["date"], content_md=e.get("content_md", ""),
                                 author="human", source="notion-backfill")
            if saved["kind"] == "note":
                ambiguous.append((name, saved))
            have.add(key)
            added += 1
    reclassified = 0
    if llm is not None and ambiguous:
        try:
            kinds = classify_entries(llm, [e for _, e in ambiguous])
            for (name, e), nk in zip(ambiguous, kinds):
                if nk != e["kind"]:
                    update_entry(cfg, name, e["id"], {"kind": nk})
                    _log(cfg).append("company.timeline_added", "joblander.classify",
                                     {"company": name, "kind": nk, "title": e["title"],
                                      "date": e["date"], "id": e["id"], "note": "LLM 终审"})
                    reclassified += 1
        except Exception:
            pass
    _log(cfg).append("timeline.backfilled", "joblander.company",
                     {"added": added, "skipped": skipped, "failed": failed,
                      "reclassified": reclassified})
    return {"added": added, "skipped": skipped, "failed": failed,
            "reclassified": reclassified}


DATE_IN_NAME = re.compile(r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})")


def bind_orphan_attachments(cfg, company: str) -> list[dict[str, str]]:
    """附件是事件的属性（2026-08-08 他定的模型）：attachments/ 里没挂到任何事件的文件，
    按文件名里的日期绑回当日事件（优先 interview/call）。绑不上的返回清单（页面提示）。幂等。"""
    entries = local_entries(cfg, company)
    referenced = {a for e in entries for a in (e.get("attachments") or [])}
    # 人工从事件上移除过的附件不得被自动绑回（否则解绑即死循环）；
    # 事件被删除时其附件同理（meta.unbound_atts）——人删了的东西系统不许顶回来
    detached = {a for e in entries for a in (e.get("detached_atts") or [])}
    detached |= set(load_meta(cfg, company).get("unbound_atts") or [])
    d = company_dir(cfg, company) / "attachments"
    if not d.exists():
        return []
    orphans: list[dict[str, str]] = []
    changed = False
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        rel = str(f.relative_to(cfg.workspace_dir))
        if rel in referenced:
            continue
        if rel in detached:
            orphans.append({"name": f.name, "rel": rel})
            continue
        target = None
        m = DATE_IN_NAME.search(f.name)
        if m:
            date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            same = [e for e in entries if e.get("date") == date]
            target = next((e for e in same if e.get("kind") in BATTLE_KINDS),
                          same[0] if same else None)
        if target is not None:
            target.setdefault("attachments", []).append(rel)
            changed = True
            _log(cfg).append("company.attachment_bound", "joblander.company",
                             {"company": company, "file": f.name,
                              "entry": target.get("id"), "date": target.get("date")})
        elif m:
            # 有日期但当日无事件：纪要本身就是该事件存在的证据 → 由附件创建事件
            date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            title = re.sub(r"^notion-|^智能纪要_|_?\d{4}年\d{1,2}月\d{1,2}日.*$|\.pdf$",
                           "", f.name).replace("_", " ").strip() or f.stem
            if changed:                    # 先落盘已改的，避免 timeline_add 覆盖
                _write_all(cfg, company, entries)
                changed = False
            timeline_add(cfg, company, kind=guess_kind(title, f.name),
                         title=title, date=date, attachments=[rel],
                         author="human", source="attachment")
            entries = local_entries(cfg, company)
            _log(cfg).append("company.attachment_bound", "joblander.company",
                             {"company": company, "file": f.name,
                              "note": "当日无事件，已由附件创建"})
        else:
            orphans.append({"name": f.name, "rel": rel})
    if changed:
        _write_all(cfg, company, entries)
    return orphans


# ---------- Notion 正文缓存（镜像层：快 + 断网可用 + 退役后即存档） ----------

def cached_body(cfg, notion_client, row: dict[str, Any], *, max_age_min: int = 10,
                force: bool = False) -> str:
    company = row.get("Company") or ""
    d = company_dir(cfg, company, create=True)
    cache = d / "notion-body.txt"
    fresh = cache.exists() and (datetime.now().timestamp() - cache.stat().st_mtime
                                < max_age_min * 60)
    if fresh and not force:
        return cache.read_text(encoding="utf-8")
    try:
        body = notion_client.page_body_text(row["notion_page_id"])
        cache.write_text(body, encoding="utf-8")
        return body
    except Exception as e:
        if cache.exists():
            return cache.read_text(encoding="utf-8")
        return f"（正文拉取失败：{e}）"


# ---------- 文件：JD 与附件 ----------

AUDIO_MIME = {".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav",
              ".ogg": "audio/ogg", ".aac": "audio/aac"}   # 面试录音（m4a=iPhone 默认）
SAFE_SUFFIX = {".pdf", ".md", ".txt", ".png", ".jpg", ".jpeg", ".html", ".docx",
               ".json", ".py", *AUDIO_MIME}

ATTACHMENT_ICON = {".pdf": "📄", ".md": "📝", ".py": "🐍", ".txt": "📃",
                   ".json": "🗒️", ".html": "🌐", ".docx": "📃",
                   ".png": "🖼️", ".jpg": "🖼️", ".jpeg": "🖼️"}


def attachment_icon(name: str) -> str:
    """附件文件名 → 展示 icon：按后缀区分，音频/未知后缀保留原样式。"""
    ext = Path(name or "").suffix.lower()
    if ext in AUDIO_MIME:
        return "🎵"
    return ATTACHMENT_ICON.get(ext, "📎")


def save_upload(cfg, company: str, filename: str, data: bytes,
                kind: str = "attachment") -> Path:
    name = re.sub(r"[^\w.\-一-鿿（）()]", "_", Path(filename).name) or "file"
    sub = "jd" if kind == "jd" else "attachments"
    d = company_dir(cfg, company, create=True) / sub
    out = d / name
    if out.exists():
        out = d / f"{out.stem}-{datetime.now(SGT).strftime('%H%M%S')}{out.suffix}"
    out.write_bytes(data)
    if kind == "jd":
        meta = load_meta(cfg, company)
        files = meta.get("jd_files") or []
        rel = str(out.relative_to(cfg.workspace_dir))
        if rel not in files:
            files.append(rel)
        patch = {"jd_files": files}
        removed = meta.get("jd_removed") or []
        if name in removed:        # 人工重新给同名文件 = 显式解除删除墓碑
            patch["jd_removed"] = [n for n in removed if n != name]
        save_meta(cfg, company, patch)
    _log(cfg).append("company.file_saved", "human_direct",
                     {"company": company, "kind": kind, "file": out.name})
    return out


def set_my_flag(cfg, company: str, on: bool) -> None:
    """「在你手上」手动旗标：他自己标记球在自己这边（自动待办算不出来的那种）。
    纯本地态（meta.my_flag），不进 Notion；作战室据此突出显示。"""
    save_meta(cfg, company, {"my_flag": bool(on)})
    _log(cfg).append("company.flag_set", "human_direct",
                     {"company": company, "on": bool(on)})


def jd_removed_names(cfg, company: str) -> set[str]:
    """人工删除过的 JD 文件名——一切自动挖掘（Notion 附件/targets 播种/链接抓取）
    不得复活它们；同名重新手动上传即解除（save_upload 处理）。"""
    return set(load_meta(cfg, company).get("jd_removed") or [])


def remove_jd_file(cfg, company: str, name: str) -> dict[str, Any]:
    """删除 JD 文件：移入 jd/.trash/（可恢复，不销毁）+ 记墓碑防自动挖掘拉回。"""
    if "/" in name or name.startswith("."):
        raise ValueError("非法文件名")
    d = company_dir(cfg, company) / "jd"
    src = d / name
    if not src.is_file():
        raise ValueError("文件不存在")
    trash = d / ".trash"
    trash.mkdir(exist_ok=True)
    dst = trash / name
    if dst.exists():
        dst = trash / f"{dst.stem}-{datetime.now(SGT).strftime('%H%M%S')}{dst.suffix}"
    src.rename(dst)
    meta = load_meta(cfg, company)
    rel = str(src.relative_to(cfg.workspace_dir))
    removed = meta.get("jd_removed") or []
    if name not in removed:
        removed.append(name)
    save_meta(cfg, company, {
        "jd_files": [f for f in (meta.get("jd_files") or []) if f != rel],
        "jd_removed": removed})
    _log(cfg).append("company.jd_removed", "human_direct",
                     {"company": company, "file": name})
    return {"removed": name, "trash": str(dst.relative_to(cfg.workspace_dir))}


EDITABLE_SUFFIX = {".md", ".txt"}


def edit_jd_file(cfg, company: str, name: str, text: str) -> dict[str, Any]:
    """改写 JD 文本文件（.md/.txt）：旧版先存 jd/.trash/（可恢复，不销毁）再覆盖。
    文件名不变、meta 不动；PDF 等二进制不可改——删了重传。"""
    if "/" in name or name.startswith("."):
        raise ValueError("非法文件名")
    if Path(name).suffix.lower() not in EDITABLE_SUFFIX:
        raise ValueError("只有 .md/.txt 可编辑；PDF 请删除后重传")
    p = company_dir(cfg, company) / "jd" / name
    if not p.is_file():
        raise ValueError("文件不存在")
    if not (text or "").strip():
        raise ValueError("内容是空的——要清掉请用删除")
    trash = p.parent / ".trash"
    trash.mkdir(exist_ok=True)
    bak = trash / (f"{p.stem}-改前-"
                   f"{datetime.now(SGT).strftime('%Y%m%d-%H%M%S')}{p.suffix}")
    bak.write_bytes(p.read_bytes())
    p.write_text(text, encoding="utf-8")
    _log(cfg).append("company.jd_edited", "human_direct",
                     {"company": company, "file": name})
    return {"edited": name, "backup": str(bak.relative_to(cfg.workspace_dir))}


def list_files(cfg, company: str, kind: str) -> list[dict[str, str]]:
    d = company_dir(cfg, company) / ("jd" if kind == "jd" else "attachments")
    if not d.exists():
        return []
    return [{"name": f.name, "rel": str(f.relative_to(cfg.workspace_dir))}
            for f in sorted(d.iterdir()) if f.is_file()]


def _file_text(p: Path) -> str:
    if p.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            return "\n".join(pg.extract_text() or "" for pg in PdfReader(str(p)).pages)
        except Exception as e:
            return f"（PDF 抽取失败：{e}）"
    if p.suffix.lower() == ".html":
        raw = p.read_text(encoding="utf-8", errors="replace")
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def jd_text(cfg, company: str) -> str:
    parts = [f"=== {f['name']} ===\n{_file_text(cfg.workspace_dir / f['rel'])[:20000]}"
             for f in list_files(cfg, company, "jd")]
    return "\n\n".join(parts)


def _download(url: str, timeout: int = 30) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (joblander)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def mine_jd(cfg, row: dict[str, Any], notion_client=None) -> tuple[str, str]:
    """JD 三级挖掘（2026-08-08 他定的优先序）：**Notion 附件 > 本地文件 > 链接抓取**。
    返回 (jd_text, 来源标注)。挖到的一律落档 jd/（幂等），下次离线可用。"""
    company = row.get("Company") or ""
    # ① Notion 页面附件（file/pdf 块）——下载落档，文件名带 notion- 前缀。
    # 纪要类附件不是 JD（2026-08-08 实锤：9 件里 6 件是豆包智能纪要）——按名排除
    NOT_JD = re.compile(r"纪要|transcript|meeting|minutes|录音|recording|复盘|面试说明",
                        re.IGNORECASE)
    if notion_client is not None and row.get("notion_page_id"):
        try:
            existing = {f["name"] for f in list_files(cfg, company, "jd")}
            removed = jd_removed_names(cfg, company)
            atts = [a for a in notion_client.page_files(row["notion_page_id"])
                    if not NOT_JD.search(a.get("name") or "")]
            named = []
            for a in atts:
                safe = re.sub(r"[^\w.\-一-鿿（）()]", "_", a["name"])[:80]
                fname = f"notion-{safe}"
                if fname in removed:       # 人工删过的不复活
                    continue
                if fname not in existing:
                    if Path(safe).suffix.lower() not in SAFE_SUFFIX:
                        continue
                    save_upload(cfg, company, fname, _download(a["url"]), kind="jd")
                named.append(fname)
            if named:
                texts = [f"=== {n} ===\n"
                         f"{_file_text(company_dir(cfg, company) / 'jd' / n)[:20000]}"
                         for n in named
                         if (company_dir(cfg, company) / 'jd' / n).exists()]
                t = "\n\n".join(texts)
                if len(t) > 200:
                    return t, f"Notion 附件（{len(named)} 件）"
        except Exception:
            pass
    # ② 本地文件：公司档案 jd/ + 私档 02-targets/jd/（按公司名匹配播种，幂等）
    _seed_from_targets(cfg, company)
    t = jd_text(cfg, company)
    if t:
        names = "、".join(f["name"] for f in list_files(cfg, company, "jd"))[:60]
        return t, f"本地文件（{names}）"
    # ③ Job URL 现抓——必须长得像 JD 才收（careers 首页/搜索页的导航垃圾不落档）。
    # 走 resolve_intake_text 与录入同一条路：MCF 用结构化 API（页面是 SPA，裸抓
    # 只有壳——2026-08-12 某支付公司报障：有链接却评出「缺 JD 原文」），其余通用抓取
    if row.get("Job URL") and not ({"jd-fetched.md", "jd-fetched.txt"}
                                   & jd_removed_names(cfg, company)):
        try:
            from joblander.scout import resolve_intake_text
            raw, _src = resolve_intake_text(cfg, row["Job URL"].strip(), "link")
            raw = raw[:6000]
            if len(raw) > 300 and _looks_like_jd(raw):
                snap = (f"# JD（Job URL 现抓）\n\n- 来源：{row['Job URL']}\n"
                        f"- 抓取：{datetime.now(SGT).strftime('%Y-%m-%d %H:%M')}"
                        f"（岗位页会过期，以原链为准）\n\n---\n\n{raw}")
                save_upload(cfg, company, "jd-fetched.md",
                            snap.encode("utf-8"), kind="jd")
                return raw, "链接抓取"
        except Exception:
            pass
    return "", "无"


JD_SIGNAL = re.compile(r"responsibilit|qualificat|requirement|minimum|preferred|"
                       r"about the (role|job)|what you.ll do|职责|任职|要求|经验|岗位描述",
                       re.IGNORECASE)


def _looks_like_jd(text: str) -> bool:
    return bool(JD_SIGNAL.search(text or ""))


def _seed_from_targets(cfg, company: str) -> int:
    """私档 JD 库（02-targets/jd/）→ 公司档案 jd/：文件名含公司名 token 即播种。
    2026-08-08 发现：他的真 JD 都攒在这个目录里，挖掘器此前只字未读。"""
    src = cfg.workspace_dir / "02-targets" / "jd"
    if not src.is_dir():
        return 0
    # 法人名样板词不进匹配 token——「PAYCORP (SINGAPORE) PTE. LTD.」若用
    # singapore/pte 去配文件名，别家 JD 全被吸进来（2026-08-12 实锤：吸走别家 JD）
    stop = {"pte", "ltd", "limited", "private", "inc", "llc", "corp",
            "corporation", "company", "holdings", "group", "singapore"}
    tokens = [w for w in re.findall(r"[a-z0-9一-鿿]+",
                                    re.split(r"[（(]", (company or "").casefold())[0])
              if (len(w) >= 3 or "一" <= w[:1] <= "鿿") and w not in stop]
    if not tokens:
        return 0
    existing = {f["name"] for f in list_files(cfg, company, "jd")}
    existing |= jd_removed_names(cfg, company)      # 人工删过的不重播
    seeded = 0
    for f in src.iterdir():
        if not f.is_file() or f.suffix.lower() not in SAFE_SUFFIX:
            continue
        fn = f.name.casefold()
        if not any(tk in fn for tk in tokens):
            continue
        name = f"targets-{re.sub(r'[^\w.一-鿿（）()-]', '_', f.name)[:70]}"
        if name in existing:
            continue
        save_upload(cfg, company, name, f.read_bytes(), kind="jd")
        seeded += 1
    return seeded


# ---------- W2 匹配评估（JD 匹配度 / 薪酬匹配度 → meta.assessment） ----------

ASSESS_SYSTEM = """你是求职作战系统的评估官（Analyst·W2）。输入：候选人材料摘要、目标岗位的 JD 与 tracker 战况、可得的薪酬信号。
输出严格 JSON（中文，专名与数字保留原文）：
{
 "jd_match": {"score": 1-5, "why": "两句话：强匹配点 + 最大缺口", "gaps": ["缺口，最多 3 条"]},
 "salary_match": {"score": 1-5 或 null, "why": "有 band/薪酬信号才打分并给对比；没有就 null 并写『无薪酬信号』"},
 "highlights": ["这个岗位对候选人的吸引点/亮点，2-4 条，一条一短句"],
 "risks": ["风险信号，最多 3 条"],
 "radar": 仅当输入含 JD 原文时输出——从 JD 提炼 4-7 个该岗位的核心能力维度：
   [{"axis": "维度名——短名词短语，≤6 个汉字或 ≤3 个英文词（如『量化研究工具』『Agent 编排』
      『RAG 与评估』）。是提炼不是摘抄：把 JD 的整句要求压成一个概念名，禁止逗号串联多概念，
      禁止『沟通能力』『团队合作』这类万金油轴", "demand": 1-5（JD 要求强度）,
     "self": 0-5（候选人材料对此维度的匹配强度——材料无证据就打低分，不猜）,
     "basis": "一句话：JD 依据 ↔ 候选人材料依据"}]
}
纪律：只依据输入材料，不编造 band；score 整数；材料不足处直说；radar 轴按该 JD 定制，不套通用模板。"""


def assess(cfg, llm, row: dict[str, Any]) -> dict[str, Any]:
    company = row.get("Company") or ""
    from joblander.sourcing import _profile_digest
    _digest = _profile_digest(cfg)                # 主源=弹药库（与初筛/画像同一对照面）
    profile_parts = [_digest] if _digest else []
    jd = jd_text(cfg, company)
    if not jd:            # 评估自己会挖：targets 播种 + Job URL 现抓（落档，下次直读）
        jd, _origin = mine_jd(cfg, row)
    if not jd and row.get("Job URL"):
        jd = f"（无本地 JD 文件，链接也抓不到正文：{row['Job URL']}——贴原文或传文件后重评）"

    signals = []
    anchor = (cfg.policy or {}).get("quote_tc_sgd")
    if anchor:
        signals.append(f"候选人对外报价锚点（总包，SGD/年）：{anchor:,}")
    evidence_lines: list[str] = []
    evidence_dated = ""
    dossier_p = cfg.workspace_dir / "14-dossiers" / f"{slugify(company)}.json"
    if dossier_p.exists():
        try:
            d = json.loads(dossier_p.read_text(encoding="utf-8"))
            signals += [f"调研信号：{s}" for s in (d.get("salary_signals") or [])[:8]]
            evidence_dated = d.get("fetched_at") or ""
            evidence_lines += [
                f"- [{f.get('category', 'other')}·{f.get('confidence', '?')}] "
                f"{f.get('claim', '')}（源：{f.get('source', '?')}）"
                for f in (d.get("facts") or [])[:24]]
            evidence_lines += [f"- [risk] {rk}" for rk in (d.get("risks") or [])[:6]]
        except Exception:
            pass

    row_slim = {k: row.get(k) for k in ("Company", "Position", "Status", "Highlight",
                                        "Next Steps", "Source")}
    evidence_block = ""
    if evidence_lines:                            # W2 证据链：判断基于 Researcher 证据
        evidence_block = (f"\n\n调研证据（Researcher 档案，抓取于 {evidence_dated or '?'}——"
                          f"信息会过期，日期久远的降权）：\n" + "\n".join(evidence_lines))
    prompt = (f"tracker 战况：{json.dumps(row_slim, ensure_ascii=False)}\n\n"
              f"薪酬信号：\n" + ("\n".join(signals) or "（无）")
              + evidence_block + "\n\n"
              f"JD：\n{(jd or '（无 JD——jd_match 按信息不足打低分并在 gaps 里写「缺 JD 原文」，不出 radar）')[:30000]}\n\n"
              f"候选人材料：\n" + ("\n\n".join(profile_parts) or "（弹药库为空）"))
    from joblander.scribe import _strip_fences
    raw = llm.generate(prompt, system=ASSESS_SYSTEM, json_mode=True)
    result = json.loads(_strip_fences(raw))
    rd = result.get("radar") or []
    if jd and len(jd) > 500 and rd and all(not x.get("demand") for x in rd):
        result.pop("radar", None)                 # JD 在手却全 0 = 坏生成，宁缺勿存垃圾
        _log(cfg).append("company.assess_degenerate", "joblander.company",
                         {"company": company, "note": "radar 全 0 已丢弃"})
    result["assessed_at"] = datetime.now(SGT).strftime("%Y-%m-%d %H:%M")

    meta = save_meta(cfg, company, {"assessment": result})
    if not meta.get("highlights") and result.get("highlights"):
        save_meta(cfg, company, {"highlights": result["highlights"]})
    jm = (result.get("jd_match") or {}).get("score")
    sm = (result.get("salary_match") or {}).get("score")

    md: list[str] = [
        f"**JD 匹配 {jm or '—'}/5**　{(result.get('jd_match') or {}).get('why', '')}"]
    md += [f"- ▸ 缺口：{g}" for g in (result.get("jd_match") or {}).get("gaps", [])]
    md += ["", f"**薪酬匹配 {sm if sm is not None else '—'}/5**　"
               f"{(result.get('salary_match') or {}).get('why', '')}"]
    rd = result.get("radar") or []
    if rd:
        md += ["", "**JD 定制雷达**（该岗位要求 vs 我的匹配，依据见备注）", "",
               "| 维度 | JD 要求 | 我 | 依据 |", "|---|---|---|---|"]
        md += [f"| {x.get('axis', '')} | {x.get('demand', '—')} | {x.get('self', '—')} "
               f"| {x.get('basis', '')} |" for x in rd]
    if result.get("highlights"):
        md += ["", "**亮点**"] + [f"- {h}" for h in result["highlights"]]
    if result.get("risks"):
        md += ["", "**风险**"] + [f"- ⚠️ {r}" for r in result["risks"]]

    timeline_upsert(cfg, company, title_prefix="评估快照", source="assess",
                    kind="assessment",
                    title=f"评估快照 · JD 匹配 {jm or '?'}/5 · 薪酬 {sm if sm is not None else '—'}",
                    summary=(result.get("jd_match") or {}).get("why", ""),
                    content_md="\n".join(md))
    _log(cfg).append("company.assessed", "joblander.company",
                     {"company": company, "jd_match": jm, "salary_match": sm})
    return result
