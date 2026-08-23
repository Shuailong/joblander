"""公司档案（company.py / ADR-14）：时间线合并、存量本地化、meta、附件、评估。全部合成数据。"""

import json

import pytest

from joblander import company as cf
from joblander.config import Config


@pytest.fixture
def cfg(tmp_path):
    return Config(raw={"workspace_dir": str(tmp_path),
                       "policy": {"quote_tc_sgd": 250000}}, path=tmp_path / "c.yaml")


def test_slugify_stable_and_safe():
    assert cf.slugify("Acme AI（新加坡）") == "Acme-AI"
    assert cf.slugify("A / B Corp") == "A---B-Corp"
    assert cf.slugify("") == "unknown"
    assert " " not in cf.slugify("a b c") and "/" not in cf.slugify("a/b")


def test_rename_company_moves_dir_and_dossier(cfg):
    """改名要带走本地档案（时间线/附件/简历版本全挂在 company_dir 下）和尽调档案，
    否则改完名字页面看起来像丢了历史。"""
    cf.timeline_add(cfg, "Acme", kind="note", title="备注", content_md="x")
    cf.save_meta(cfg, "Acme", {"resume_variant": "v1"})
    ddir = cfg.workspace_dir / "14-dossiers"
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "Acme.json").write_text('{"card": ["x"]}', encoding="utf-8")

    cf.rename_company(cfg, "Acme", "Acme Corp")

    assert not (cfg.workspace_dir / "18-companies" / "Acme").exists()
    assert cf.load_meta(cfg, "Acme Corp").get("resume_variant") == "v1"
    assert cf.local_entries(cfg, "Acme Corp")[0]["title"] == "备注"
    assert (ddir / "Acme-Corp.json").exists() and not (ddir / "Acme.json").exists()
    log = (cfg.workspace_dir / "08-events" / "event-log.jsonl").read_text()
    assert "company.renamed" in log


def test_rename_company_rejects_slug_collision(cfg):
    """目标 slug 本地已有档案（撞名）时拒绝——不悄悄合并成一家，数据会串。"""
    cf.save_meta(cfg, "Acme", {"x": 1})
    cf.save_meta(cfg, "Acme Corp", {"x": 2})
    with pytest.raises(ValueError):
        cf.rename_company(cfg, "Acme", "Acme Corp")
    assert (cfg.workspace_dir / "18-companies" / "Acme").exists()   # 没动


def test_rename_company_noop_when_slug_unchanged(cfg):
    """只改大小写/空格这类不影响 slug 的改动——不折腾目录。"""
    cf.save_meta(cfg, "Acme", {"x": 1})
    cf.rename_company(cfg, "Acme", "Acme")   # slug 相同
    assert cf.load_meta(cfg, "Acme").get("x") == 1


def test_timeline_roundtrip_and_event(cfg):
    e = cf.timeline_add(cfg, "Acme", kind="call", title="HM 电话",
                        participants=["Ann"], content_md="聊了 team", author="human")
    entries = cf.local_entries(cfg, "Acme")
    assert len(entries) == 1 and entries[0]["id"] == e["id"]
    assert entries[0]["author"] == "human" and entries[0]["participants"] == ["Ann"]
    log = (cfg.workspace_dir / "08-events" / "event-log.jsonl").read_text()
    assert "company.timeline_added" in log


def test_parse_notion_entries_and_kind_guess():
    body = ("前言不属于时间线\n\n### 2026-08-01 一面/王某\n聊得不错\n带两行\n"
            "### 2026-07-28 HM 电话\n约了下周")
    out = cf.parse_notion_entries(body)
    assert [e["date"] for e in out] == ["2026-08-01", "2026-07-28"]
    assert out[0]["kind"] == "interview" and out[1]["kind"] == "call"
    assert "带两行" in out[0]["content_md"]
    assert all(e["source"] == "notion" for e in out)


def test_merged_timeline_dedupe_local_wins(cfg):
    cf.timeline_add(cfg, "Acme", kind="interview", title="一面/王某",
                    date="2026-08-01", content_md="本地版", author="ai", source="scribe")
    body = "### 2026-08-01 一面/王某\nnotion 版\n### 2026-07-20 入池\n渠道 referral"
    merged = cf.merged_timeline(cfg, "Acme", notion_body=body)
    assert len(merged) == 2                       # 同 (日期,标题) 去重
    assert merged[0]["date"] == "2026-08-01"      # 倒序
    assert merged[0]["content_md"] == "本地版" and merged[0].get("also_in_notion")
    assert merged[1]["source"] == "notion"


def test_review_materializes_notion_entry(cfg):
    """给 Notion 存量条目补复盘 → 物化为本地条目（存量渐进迁移的机制）。"""
    e = cf.set_review(cfg, "Acme", entry_id="", date="2026-08-01",
                      title="一面/王某", text="失手：band 没问到数字")
    assert e["my_review"]["text"].startswith("失手")
    merged = cf.merged_timeline(cfg, "Acme",
                                notion_body="### 2026-08-01 一面/王某\n原文")
    assert len(merged) == 1 and merged[0]["my_review"]["text"]


def test_review_on_existing_entry(cfg):
    e = cf.timeline_add(cfg, "Acme", kind="interview", title="二面")
    cf.set_review(cfg, "Acme", entry_id=e["id"], text="打得稳")
    assert cf.local_entries(cfg, "Acme")[0]["my_review"]["text"] == "打得稳"


def test_add_from_markdown_parses_header(cfg):
    e = cf.add_from_markdown(cfg, "Acme", "### 2026-08-05 二面/李某\n\n【录入】…",
                             ref="prop.json")
    assert e["date"] == "2026-08-05" and e["kind"] == "interview"
    assert e["title"] == "二面/李某" and e["author"] == "ai" and e["ref"] == "prop.json"


def test_save_upload_jd_updates_meta_and_intake_date(cfg):
    cf.save_upload(cfg, "Acme", "jd v1.pdf", b"%PDF-fake", kind="jd")
    meta = cf.load_meta(cfg, "Acme")
    assert len(meta["jd_files"]) == 1 and meta["jd_files"][0].endswith(".pdf")
    # intake_date：meta 覆盖 > Notion created > 时间线最早
    row = {"Company": "Acme", "created": "2026-07-15T08:00:00Z"}
    assert cf.intake_date(cfg, row) == "2026-07-15"
    cf.save_meta(cfg, "Acme", {"intake_date": "2026-07-01"})
    assert cf.intake_date(cfg, row) == "2026-07-01"


def test_assess_writes_meta_and_timeline(cfg):
    class FakeLLM:
        def generate(self, prompt, system=None, json_mode=False):
            assert "250,000" in prompt            # 锚点来自 policy，不是硬编码
            return json.dumps({"jd_match": {"score": 4, "why": "强匹配", "gaps": ["缺 JD"]},
                               "salary_match": {"score": None, "why": "无薪酬信号"},
                               "highlights": ["平台大"], "risks": []})
    row = {"Company": "Acme", "Position": "MLE", "Status": "Applied"}
    result = cf.assess(cfg, FakeLLM(), row)
    assert result["jd_match"]["score"] == 4
    meta = cf.load_meta(cfg, "Acme")
    assert meta["assessment"]["jd_match"]["score"] == 4
    assert meta["highlights"] == ["平台大"]       # 亮点为空时自动带入
    kinds = [e["kind"] for e in cf.local_entries(cfg, "Acme")]
    assert "assessment" in kinds


def test_guess_kind_reads_content_not_just_title():
    """他的标题常常只有人名——类型信号在正文里（2026-08-08 教训）。"""
    assert cf.guess_kind("Alex 2PM", "recruiter 通话，聊了 team 和 band") == "call"
    assert cf.guess_kind("记录", "band 230k，HM Frank；通话速记") == "call"
    assert cf.guess_kind("一面/王某", "") == "interview"
    assert cf.guess_kind("入池", "WhatsApp 扫读发现") == "note"
    assert cf.guess_kind("已投递（官网 / Ashby）", "") == "apply"
    assert cf.guess_kind("OA 笔试通知", "") == "oa"
    assert cf.guess_kind("下一步", "对方发来 HackerRank 链接，72h 内完成") == "oa"
    assert cf.guess_kind("周进展", "已投递 3 家，等回复") == "note"   # 投递只认标题


def test_classify_entries_alignment_by_index():
    """LLM 批量分类按 i 回传防错位；缺失的保持原 kind（宁不改不错改）。"""
    class L:
        def generate(self, prompt, system=None, json_mode=False):
            return ('{"kinds": [{"i": 1, "kind": "call"}, {"i": 0, "kind": "note"}]}')
    items = [{"title": "a", "content_md": "", "kind": "interview"},
             {"title": "b", "content_md": "", "kind": "note"},
             {"title": "c", "content_md": "", "kind": "email"}]
    assert cf.classify_entries(L(), items) == ["note", "call", "email"]


def test_build_capability_pipeline(cfg):
    """能力画像：JD 语料 + 复盘证据 + 差距信号 → 维度/双分/prep，落 capability.json。"""
    (cfg.workspace_dir / "09-projections").mkdir()
    (cfg.workspace_dir / "09-projections" / "tracker.json").write_text(json.dumps(
        {"rows": [{"Company": "Acme", "Position": "MLE", "Status": "Applied",
                   "Priority": "High"},
                  {"Company": "Noise Co", "Position": "PM", "Status": "Applied",
                   "Priority": "Low"}]}))
    cf.save_upload(cfg, "Acme", "jd.txt", b"need kubernetes and LLM serving", kind="jd")
    cf.save_upload(cfg, "Noise Co", "jd.txt", b"need powerpoint skills", kind="jd")
    cf.timeline_add(cfg, "Acme", kind="interview", title="R1",
                    content_md="RAG 答得顺，K8s 卡壳", author="ai", source="scribe")

    class CapLLM:
        def generate(self, prompt, system=None, json_mode=False):
            assert "kubernetes" in prompt and "K8s 卡壳" in prompt   # 两路语料都进了
            assert "powerpoint" not in prompt    # 市场侧只取 High 优先级的 JD
            return json.dumps({"dimensions": [
                {"name": "LLM 服务", "market": 5, "self": 4,
                 "evidence": ["RAG 答得顺"], "gap": "", "prep": []},
                {"name": "K8s", "market": 4, "self": 2, "evidence": ["K8s 卡壳"],
                 "gap": "集群运维弱", "prep": ["搭 3 节点集群"]}],
                "strengths": ["LLM 服务"], "focus": ["K8s"], "summary": "补 K8s"})
    from joblander.capability import build_capability, load_capability
    data = build_capability(cfg, CapLLM())
    assert len(data["dimensions"]) == 2 and data["sources"]["evidence_n"] == 1
    assert load_capability(cfg)["dimensions"][1]["prep"] == ["搭 3 节点集群"]
    log = (cfg.workspace_dir / "08-events" / "event-log.jsonl").read_text()
    assert "capability.built" in log


def test_edit_entry_local_and_notion_materialize(cfg):
    """事件可编辑：本地条目原位改留痕；Notion 存量条目物化后改，原文不丢。"""
    e = cf.timeline_add(cfg, "Acme", kind="note", title="Ann 2PM",
                        date="2026-08-05", content_md="聊了 team 结构")
    hit = cf.edit_entry(cfg, "Acme", entry_id=e["id"],
                        fields={"kind": "call", "participants": ["Ann"],
                                "summary": "HR 初聊"})
    assert hit["kind"] == "call" and hit["participants"] == ["Ann"]
    assert hit["content_md"] == "聊了 team 结构"          # 未提交的字段不动
    assert hit["human_edited"]
    stored = cf.local_entries(cfg, "Acme")[0]
    assert stored["kind"] == "call" and stored["summary"] == "HR 初聊"

    # Notion 存量（无本地 id）：物化 + 应用修改，原文随物化带入
    got = cf.edit_entry(cfg, "Acme", entry_id="", date="2026-08-01", title="R1 面试",
                        fields={"kind": "interview", "content_md": "问了 RAG",
                                "title": "R1 技术面"})
    assert got["kind"] == "interview" and got["content_md"] == "问了 RAG"
    assert got["title"] == "R1 技术面" and got["author"] == "human"

    with pytest.raises(ValueError):
        cf.edit_entry(cfg, "Acme", entry_id=e["id"], fields={"nope": 1})
    with pytest.raises(ValueError):
        cf.edit_entry(cfg, "Acme", entry_id=e["id"], fields={"kind": "武器"})


def test_edit_entry_rename_tombstones_old_key(cfg):
    """改名/改期记旧键墓碑：Notion 同键存量不再被合并流带回——
    否则「编辑保存」在页面上看起来就是新建了一条、原条目还在（2026-08-10 用户报障）。"""
    body = ("### 2026-08-01 R1 面试\n\n问了 RAG\n\n"
            "### 2026-08-02 HR call\n\n聊薪酬")
    # 物化 + 改名：改后的在档，Notion 原键不再冒回
    cf.edit_entry(cfg, "Acme", entry_id="", date="2026-08-01", title="R1 面试",
                  fields={"title": "R1 技术面", "content_md": "问了 RAG"})
    tl = cf.merged_timeline(cfg, "Acme", notion_body=body)
    assert [e["title"] for e in tl if e["date"] == "2026-08-01"] == ["R1 技术面"]

    # 物化不改键：不记墓碑，本地优先 + also_in_notion 配对如常
    cf.edit_entry(cfg, "Acme", entry_id="", date="2026-08-02", title="HR call",
                  fields={"kind": "call", "content_md": "聊薪酬"})
    tl = cf.merged_timeline(cfg, "Acme", notion_body=body)
    d2 = [e for e in tl if e["date"] == "2026-08-02"]
    assert len(d2) == 1 and d2[0]["also_in_notion"] and d2[0]["author"] == "human"

    # 原位改名：本地条目失去同键配对后，Notion 存量同样不能再现
    loc = next(x for x in cf.local_entries(cfg, "Acme") if x["title"] == "HR call")
    cf.edit_entry(cfg, "Acme", entry_id=loc["id"], fields={"title": "HR 初聊"})
    tl = cf.merged_timeline(cfg, "Acme", notion_body=body)
    assert [e["title"] for e in tl if e["date"] == "2026-08-02"] == ["HR 初聊"]


def test_backfill_preserves_order_and_tombstones(cfg):
    """回填按正文倒序落库（ts 递增）：同日多条展示仍是正文原顺序；
    墓碑键（已删/已改名）不回填；幂等重跑不重复。"""
    class FakeNotion:
        def page_body_text(self, pid):
            return ("### 2026-08-03 下午战报\n\nB 段\n\n"
                    "### 2026-08-03 上午战报\n\nA 段\n\n"
                    "### 2026-08-02 已删条目\n\n旧内容")
    cf._add_tombstone(cfg, "Orderly", "2026-08-02", "已删条目")
    rows = [{"Company": "Orderly", "notion_page_id": "p1", "Status": "Applied"}]
    out = cf.backfill_from_notion(cfg, FakeNotion(), rows)
    assert out["added"] == 2 and out["skipped"] == 1
    tl = cf.merged_timeline(cfg, "Orderly")
    assert [e["title"] for e in tl] == ["下午战报", "上午战报"]   # 展示顺序 = 正文顺序
    assert cf.backfill_from_notion(cfg, FakeNotion(), rows)["added"] == 0


def test_capability_jd_scope_custom(cfg):
    """JD 策略：custom 点名清单替代 High 过滤（Low 的也能点名），跨重估存续。"""
    from joblander.capability import build_capability, load_capability, set_scope
    (cfg.workspace_dir / "09-projections").mkdir()
    (cfg.workspace_dir / "09-projections" / "tracker.json").write_text(json.dumps(
        {"rows": [{"Company": "Acme", "Position": "MLE", "Status": "Applied",
                   "Priority": "High"},
                  {"Company": "Noise Co", "Position": "PM", "Status": "Applied",
                   "Priority": "Low"}]}))
    cf.save_upload(cfg, "Acme", "jd.txt", b"need kubernetes and LLM serving", kind="jd")
    cf.save_upload(cfg, "Noise Co", "jd.txt", b"need powerpoint skills", kind="jd")
    set_scope(cfg, "custom", ["Noise Co"])

    class L:
        def generate(self, prompt, system=None, json_mode=False):
            assert "powerpoint" in prompt and "kubernetes" not in prompt
            assert "自定义清单：Noise Co" in prompt
            return json.dumps({"dimensions": [{"name": "x", "market": 3, "self": 3,
                                               "evidence": [], "gap": "", "prep": []}],
                               "strengths": [], "focus": [], "summary": "s"})
    build_capability(cfg, L())
    cap = load_capability(cfg)
    assert cap["jd_scope"] == {"mode": "custom", "companies": ["Noise Co"]}
    assert cap["sources"]["jd_mode"] == "custom"
    build_capability(cfg, L())                    # 重估后策略存续
    assert load_capability(cfg)["jd_scope"]["mode"] == "custom"
    with pytest.raises(ValueError):
        set_scope(cfg, "custom", [])
    with pytest.raises(ValueError):
        set_scope(cfg, "nope")


def test_mine_jd_priority_notion_local_link(cfg, monkeypatch):
    """JD 三级挖掘优先序：Notion 附件 > 本地文件 > 链接抓取，来源标注随行。"""
    row = {"Company": "Acme", "notion_page_id": "p1", "Job URL": "https://x.test/jd"}

    class FakeNotion:
        def page_files(self, page_id):
            return [{"name": "智能纪要_面试_0806.pdf", "url": "https://s3.test/memo"},
                    {"name": "jd-official.txt", "url": "https://s3.test/signed"}]
    monkeypatch.setattr(cf, "_download",
                        lambda url, timeout=30: b"official jd from notion, kubernetes required, " * 8)
    t, origin = cf.mine_jd(cfg, row, notion_client=FakeNotion())
    assert "official jd from notion" in t and origin.startswith("Notion 附件")

    row2 = {"Company": "Beta", "notion_page_id": None, "Job URL": None}
    cf.save_upload(cfg, "Beta", "jd.txt", b"local jd text here", kind="jd")
    t2, o2 = cf.mine_jd(cfg, row2)
    assert "local jd" in t2 and o2.startswith("本地文件")

    row3 = {"Company": "Gamma", "Job URL": "https://y.test/jd"}
    monkeypatch.setattr("joblander.researcher.fetch_url",
                        lambda u, timeout=20: "Responsibilities: fetched jd body " * 20)
    t3, o3 = cf.mine_jd(cfg, row3)
    assert o3 == "链接抓取" and "fetched jd" in t3

    t4, o4 = cf.mine_jd(cfg, {"Company": "Delta"})
    assert (t4, o4) == ("", "无")


def test_capability_override_survives_rebuild(cfg):
    """人工校准是权威：手调分覆盖 LLM 分、跨重估存续、LLM 原分留档对照。"""
    from joblander.capability import build_capability, load_capability, set_override
    (cfg.workspace_dir / "09-projections").mkdir()
    (cfg.workspace_dir / "09-projections" / "tracker.json").write_text(
        json.dumps({"rows": []}))

    class L:
        def generate(self, prompt, system=None, json_mode=False):
            if "系统设计：self=3" in prompt:      # 重估时校准以权威身份进入 prompt
                self.saw_override = True
            return json.dumps({"dimensions": [
                {"name": "系统设计", "market": 5, "self": 4,
                 "subs": [{"name": "抽象与类建模", "self": 3, "note": "面试暴露不精确"}],
                 "evidence": ["某场系统设计面"], "gap": "", "prep": []}],
                "strengths": [], "focus": [], "summary": "x"})
    llm = L()
    build_capability(cfg, llm)
    set_override(cfg, "系统设计", 3, "Google 面后自评：抽象建模不精确")
    cap = load_capability(cfg)
    d = cap["dimensions"][0]
    assert d["self"] == 3 and d["self_llm"] == 4 and "Google" in d["override_note"]
    build_capability(cfg, llm)                    # 重估
    cap2 = load_capability(cfg)
    assert cap2["dimensions"][0]["self"] == 3     # 校准存续，未被 LLM 推翻
    assert getattr(llm, "saw_override", False)    # 且校准进了重估上下文
    assert cap2["dimensions"][0]["subs"][0]["name"] == "抽象与类建模"


def test_assess_jd_custom_radar_and_upsert(cfg):
    """雷达轴从该 JD 定制提炼（demand+self 同跳给出）；评估条目 upsert 不堆重复，
    内容带定制雷达表格。"""
    cf.save_upload(cfg, "Acme", "jd.txt", b"heavy LLM agent work, quant research tools", kind="jd")

    class L:
        def __init__(self): self.n = 0
        def generate(self, prompt, system=None, json_mode=False):
            self.n += 1
            assert "能力轴清单" not in prompt                  # 画像轴注入已废弃
            return json.dumps({"jd_match": {"score": 4, "why": f"v{self.n}", "gaps": ["缺量化经验"]},
                               "salary_match": {"score": None, "why": "无薪酬信号"},
                               "highlights": [], "risks": [],
                               "radar": [{"axis": "Agent 编排", "demand": 5, "self": 4,
                                          "basis": "JD 主体 ↔ 平台战绩"},
                                         {"axis": "量化研究工具", "demand": 4, "self": 2,
                                          "basis": "JD 明列 ↔ 材料无证据"}]})
    llm = L()
    cf.assess(cfg, llm, {"Company": "Acme", "Position": "MLE"})
    a = cf.load_meta(cfg, "Acme")["assessment"]
    assert a["radar"][0]["axis"] == "Agent 编排" and a["radar"][1]["self"] == 2
    cf.assess(cfg, llm, {"Company": "Acme", "Position": "MLE"})   # 重评
    snaps = [e for e in cf.local_entries(cfg, "Acme")
             if (e.get("title") or "").startswith("评估快照")]
    assert len(snaps) == 1                                        # upsert：一条不堆
    assert "| 维度 | JD 要求 | 我 |" in snaps[0]["content_md"]    # 定制雷达表格
    assert "量化研究工具" in snaps[0]["content_md"] and "v2" in snaps[0]["content_md"]


def test_assess_radar_all_zero_dropped(cfg):
    """JD 在手却全 0 的 radar = 坏生成，宁缺勿存。"""
    cf.save_upload(cfg, "Zed", "jd.txt", b"x" * 600, kind="jd")

    class L:
        def generate(self, prompt, system=None, json_mode=False):
            return json.dumps({"jd_match": {"score": 3, "why": "", "gaps": []},
                               "salary_match": {"score": None, "why": ""},
                               "highlights": [], "risks": [],
                               "radar": [{"axis": "A", "demand": 0, "self": 0, "basis": ""}]})
    cf.assess(cfg, L(), {"Company": "Zed"})
    assert "radar" not in cf.load_meta(cfg, "Zed")["assessment"]


def test_review_materialization_preserves_content_and_kind(cfg):
    """review 修复回归：物化 Notion 存量条目必须带原文与类型，否则本地空壳
    在合并去重时胜出、纪要正文从页面消失（数据丢失路径）。"""
    from joblander.company import merged_timeline, set_review
    body = "### 2026-08-05 Google Interview Day\n面了三轮，系统设计被问抽象建模"
    e = set_review(cfg, "Google-Cloud", entry_id="", date="2026-08-05",
                   title="Google Interview Day", text="抽象建模答得不精确",
                   content_md="面了三轮，系统设计被问抽象建模", kind="interview")
    assert e["kind"] == "interview"
    merged = merged_timeline(cfg, "Google-Cloud", notion_body=body)
    assert len(merged) == 1
    assert "抽象建模" in merged[0]["content_md"]          # 原文保住了
    assert merged[0]["my_review"]["text"].startswith("抽象建模答得")


def test_mine_jd_excludes_meeting_memos(cfg, monkeypatch):
    """Notion 附件里的纪要不是 JD（豆包智能纪要误吞实锤）——按名排除，全是纪要则降级本地/链接。"""
    class MemoOnly:
        def page_files(self, page_id):
            return [{"name": "智能纪要_二面_0731.pdf", "url": "https://s3.test/m"}]
    row = {"Company": "Zeta", "notion_page_id": "p9", "Job URL": None}
    t_, o_ = cf.mine_jd(cfg, row, notion_client=MemoOnly())
    assert (t_, o_) == ("", "无")                 # 纪要被拒，无其他来源
    assert not (cf.company_dir(cfg, "Zeta") / "jd").exists() or         not any((cf.company_dir(cfg, "Zeta") / "jd").iterdir())


def test_suggest_fields_from_note(cfg):
    """人工记录 → 字段建议提案：只提确有变化的字段，无建议返回 None。"""
    from joblander.scribe import suggest_fields
    row = {"Company": "Acme", "notion_page_id": "p1", "Status": "Applied",
           "Next Steps": "等回复"}

    class L:
        def generate(self, prompt, system=None, json_mode=False):
            assert "等回复" in prompt
            return json.dumps({"field_diffs": {
                "Status": "Interview Scheduled", "Next Steps": "准备周四二面",
                "Highlight": None}})
    out = suggest_fields(cfg, L(), row, "HR 来电确认周四 14:00 二面", ref="tl-1")
    prop = json.loads(out.read_text(encoding="utf-8"))
    assert prop["origin"] == "note.suggest" and prop["approved"] is None
    assert prop["field_diffs"] == {"Status": "Interview Scheduled",
                                   "Next Steps": "准备周四二面"}

    class Empty:
        def generate(self, prompt, system=None, json_mode=False):
            return json.dumps({"field_diffs": {"Status": "Applied"}})   # 与现值相同
    assert suggest_fields(cfg, Empty(), row, "随手一句") is None


def test_seed_from_targets_and_jd_validation(cfg, monkeypatch):
    """本地层扫私档 02-targets/jd（按公司名播种，幂等）；链接层拒收导航垃圾。"""
    src = cfg.workspace_dir / "02-targets" / "jd"
    src.mkdir(parents=True)
    (src / "acme-fde-genai.md").write_text("Responsibilities: build ml", encoding="utf-8")
    (src / "other-co-role.md").write_text("x", encoding="utf-8")
    row = {"Company": "Acme AI", "notion_page_id": None, "Job URL": None}
    t, o = cf.mine_jd(cfg, row)
    assert "Responsibilities" in t and o.startswith("本地文件")
    assert cf.mine_jd(cfg, row)[1].startswith("本地文件")     # 幂等不重复播种
    files = cf.list_files(cfg, "Acme AI", "jd")
    assert len(files) == 1 and files[0]["name"].startswith("targets-")

    row2 = {"Company": "Zed", "Job URL": "https://z.test/jd"}
    monkeypatch.setattr("joblander.researcher.fetch_url",
                        lambda u, timeout=20: "Careers Home Jobs Sign in Help " * 40)
    assert cf.mine_jd(cfg, row2) == ("", "无")                # 导航垃圾拒收


def test_bind_orphan_attachments(cfg):
    """附件是事件的属性：按文件名日期绑回当日事件；当日无事件则由附件创建事件。"""
    from joblander.company import bind_orphan_attachments, local_entries
    cf.timeline_add(cfg, "Acme", kind="interview", title="二面", date="2026-08-05")
    att = cf.company_dir(cfg, "Acme", create=True) / "attachments"
    (att / "智能纪要_二面_2026年8月5日.pdf").write_bytes(b"%PDF")
    (att / "备忘_2026年8月9日.pdf").write_bytes(b"%PDF")     # 当日无事件
    (att / "undated-note.pdf").write_bytes(b"%PDF")          # 无日期 → 孤儿
    orphans = bind_orphan_attachments(cfg, "Acme")
    assert [o["name"] for o in orphans] == ["undated-note.pdf"]
    entries = {e["date"]: e for e in local_entries(cfg, "Acme")}
    assert entries["2026-08-05"]["attachments"][0].endswith("二面_2026年8月5日.pdf")
    assert entries["2026-08-09"]["source"] == "attachment"   # 由附件创建
    assert bind_orphan_attachments(cfg, "Acme") == orphans   # 幂等


def test_delete_entry_tombstones_attachments(cfg):
    """删除带附件的事件后，绑回器不得用游离附件把它复活（2026-08-11 报障：
    删 5 次被顶回 5 次）。文件不销毁，转为未绑附件展示。"""
    from joblander.company import bind_orphan_attachments, local_entries
    att = cf.company_dir(cfg, "Acme", create=True) / "attachments"
    (att / "Screenshot_2026-08-09_at_11.06.41_PM.png").write_bytes(b"\x89PNG")
    bind_orphan_attachments(cfg, "Acme")                     # 由附件自动创建事件
    e = local_entries(cfg, "Acme")[0]
    assert e["source"] == "attachment" and e["attachments"]
    cf.delete_entry(cfg, "Acme", entry_id=e["id"])
    orphans = bind_orphan_attachments(cfg, "Acme")           # 再跑绑回 = 页面刷新
    assert local_entries(cfg, "Acme") == []                  # 事件没有被复活
    assert [o["name"] for o in orphans] == ["Screenshot_2026-08-09_at_11.06.41_PM.png"]
    assert (att / "Screenshot_2026-08-09_at_11.06.41_PM.png").exists()   # 文件保留


def test_seed_sanitizer_keeps_case_and_digits(cfg):
    """播种清洗正则回归：大写与数字不得打成下划线（2026-08-11 实锤：双反斜杠
    把字符类解析歪，JD-chatbot-NOVA.docx 播成了 targets-__-chatbot-___.docx）。"""
    src = cfg.workspace_dir / "02-targets" / "jd"
    src.mkdir(parents=True)
    (src / "JD-chatbot-NOVA 2.docx").write_bytes(b"x" * 10)
    cf._seed_from_targets(cfg, "NOVA")
    names = {f["name"] for f in cf.list_files(cfg, "NOVA", "jd")}
    assert names == {"targets-JD-chatbot-NOVA_2.docx"}


def test_seed_ignores_legal_name_boilerplate(cfg):
    """法人名样板词不参与播种匹配（2026-08-12 实锤：PAYCORP (SINGAPORE)
    PTE. LTD. 的 singapore token 把 别家公司的 JD 吸进了 PAYCORP 档案）。"""
    src = cfg.workspace_dir / "02-targets" / "jd"
    src.mkdir(parents=True)
    (src / "OtherCo_AI_Singapore.pdf").write_bytes(b"x" * 10)
    (src / "paycorp-senior-ai.pdf").write_bytes(b"y" * 10)
    cf._seed_from_targets(cfg, "PAYCORP (SINGAPORE) PTE. LTD.")
    names = {f["name"] for f in
             cf.list_files(cfg, "PAYCORP (SINGAPORE) PTE. LTD.", "jd")}
    assert names == {"targets-paycorp-senior-ai.pdf"}   # 别家的 Singapore JD 不吸


def test_jd_removed_tombstone_blocks_mining(cfg, monkeypatch):
    """删过的 JD 文件不复活：targets 播种与 Job URL 现抓都尊重墓碑；
    同名重新手动上传 = 显式解除。"""
    src = cfg.workspace_dir / "02-targets" / "jd"
    src.mkdir(parents=True)
    (src / "acme-role.txt").write_text("Responsibilities: build LLM. " * 20,
                                       encoding="utf-8")
    row = {"Company": "Acme", "Job URL": "https://acme.example/jd"}
    monkeypatch.setattr("joblander.researcher.fetch_url",
                        lambda u, timeout=20: "Requirements: minimum 5 yoe. " * 30)
    _, origin = cf.mine_jd(cfg, row)
    assert "targets-acme-role.txt" in origin          # 播种进来了

    cf.remove_jd_file(cfg, "Acme", "targets-acme-role.txt")
    _, origin2 = cf.mine_jd(cfg, row)
    assert origin2 == "链接抓取"                       # 播种没拉回，退到现抓
    assert "targets-acme-role.txt" not in {f["name"]
                                           for f in cf.list_files(cfg, "Acme", "jd")}

    cf.remove_jd_file(cfg, "Acme", "jd-fetched.md")
    t3, origin3 = cf.mine_jd(cfg, row)
    assert (t3, origin3) == ("", "无")                # 现抓也尊重墓碑

    cf.save_upload(cfg, "Acme", "jd-fetched.md", b"manual again", kind="jd")
    assert "jd-fetched.md" not in cf.jd_removed_names(cfg, "Acme")   # 手动重给解除


def test_mine_jd_mcf_link_via_structured_api(cfg, monkeypatch):
    """MCF 链接现抓走结构化 API——页面是 SPA 裸抓只有壳（2026-08-12 某支付公司
    报障：明明有 JD 链接，评估却说缺 JD 原文）；薪资/年限/技能随详情一起入档。"""
    monkeypatch.setattr("joblander.sourcing.mcf_job_detail", lambda uid, timeout=20: {
        "title": "Senior AI Engineer",
        "postedCompany": {"name": "PAYCORP (SINGAPORE) PTE. LTD."},
        "salary": {"minimum": 10000, "maximum": 17000,
                   "type": {"salaryType": "Monthly"}},
        "minimumYearsExperience": 5, "skills": [{"skill": "LLM"}],
        "description": "<p>Responsibilities: build the GenAI platform.</p>" * 10})
    row = {"Company": "PAYCORP (SINGAPORE) PTE. LTD.",
           "Job URL": "https://www.mycareersfuture.gov.sg/job/information-technology/"
                      "senior-ai-engineer-paycorp-9d28e302a365b47b2954b71a5daba336"}
    t, origin = cf.mine_jd(cfg, row)
    assert origin == "链接抓取"
    assert "10000-17000" in t and "Responsibilities" in t     # 结构化薪资 + 正文
    files = {f["name"] for f in cf.list_files(cfg, row["Company"], "jd")}
    assert "jd-fetched.md" in files                           # 落档，下次直读


def test_assess_mines_jd_when_archive_empty(cfg, monkeypatch):
    """评估自挖兜底：jd/ 为空但有 Job URL → 现挖再评，不再拿着链接说没 JD。"""
    monkeypatch.setattr("joblander.researcher.fetch_url",
                        lambda u, timeout=20: "Requirements: LLM systems. " * 30)
    seen = {}

    class L:
        def generate(self, prompt, system=None, json_mode=False):
            seen["prompt"] = prompt
            return json.dumps({"jd_match": {"score": 4, "why": "ok", "gaps": []},
                               "salary_match": {"score": None, "why": "无"},
                               "highlights": [], "risks": []})
    cf.assess(cfg, L(), {"Company": "Acme", "Position": "MLE", "Status": "Applied",
                         "Job URL": "https://acme.example/careers/mle"})
    assert "Requirements: LLM systems." in seen["prompt"]     # 现挖的 JD 进了评估
    assert "无本地 JD 文件" not in seen["prompt"]


def test_assess_cites_researcher_evidence(cfg):
    """W2 证据链：dossier 的 facts/risks 带来源与日期进评估 prompt。"""
    ddir = cfg.workspace_dir / "14-dossiers"
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "Acme.json").write_text(json.dumps({
        "fetched_at": "2026-08-01",
        "facts": [{"claim": "B 轮后裁员 10%", "category": "stability",
                   "source": "新闻页", "confidence": "high"}],
        "risks": ["组织不稳"],
        "salary_signals": ["JD 写 range 面议"]}, ensure_ascii=False), encoding="utf-8")

    seen = {}

    class L:
        def generate(self, prompt, system=None, json_mode=False):
            seen["prompt"] = prompt
            return json.dumps({"jd_match": {"score": 3, "why": "", "gaps": []},
                               "salary_match": {"score": None, "why": ""}, "risks": []})
    row = {"Company": "Acme", "notion_page_id": "p1", "Status": "Applied"}
    cf.assess(cfg, L(), row)
    assert "调研证据" in seen["prompt"] and "2026-08-01" in seen["prompt"]
    assert "B 轮后裁员 10%" in seen["prompt"] and "（源：新闻页）" in seen["prompt"]
    assert "[risk] 组织不稳" in seen["prompt"]
