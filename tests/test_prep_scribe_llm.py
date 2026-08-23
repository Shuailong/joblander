"""Prep / Scribe / LLM / 写回 builders 单测 —— 全合成数据，公开可跑。"""

import json

import pytest
import yaml

from joblander.config import Config
from joblander.llm import LLMError, MockLLM
from joblander.notion import build_prop, markdown_to_blocks
from joblander.prep import build_brief, find_row
from joblander.scribe import run_scribe

ROWS = [
    {"notion_page_id": "p1", "Company": "Acme AI", "Position": "Engineer",
     "Status": "Interview Scheduled", "Priority": "High", "Source": "Referral",
     "Contact Person": "Ann", "Contact Info": "email", "Next Steps": "prep round 2",
     "Highlight": "strong fit", "Feedback": "R1 went well", "Job URL": None,
     "Follow-up Reminder": "2026-08-12"},
    {"notion_page_id": "p2", "Company": "Beta Corp", "Status": "Applied"},
]

PLAYBOOK = [
    {"id": "P1", "pattern": "tenure question", "status": "needs_work",
     "best_answer": "use the standard 30s answer"},
    {"id": "P7", "pattern": "pre-flight", "status": "needs_work",
     "best_answer": "close autocomplete; test platform"},
    {"id": "P8", "pattern": "ask numbers", "status": "solid", "best_answer": "-"},
]

RULES = [{"id": "codename", "type": "pattern", "action": "block",
          "audiences": ["outbound", "internal"], "patterns": ["ProjectX"], "why": "内部代号"}]


@pytest.fixture
def cfg(tmp_path):
    ws = tmp_path / "ws"
    (ws / "09-projections").mkdir(parents=True)
    (ws / "03-materials").mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text(
        json.dumps({"rows": ROWS}), encoding="utf-8")
    (ws / "03-materials" / "playbook.yaml").write_text(
        yaml.safe_dump(PLAYBOOK, allow_unicode=True), encoding="utf-8")
    return Config(raw={"workspace_dir": str(ws), "sentinel": {"rules": RULES}},
                  path=tmp_path / "config.yaml")


def test_find_row_exact_and_partial():
    assert find_row(ROWS, "acme ai")["notion_page_id"] == "p1"
    assert find_row(ROWS, "beta")["notion_page_id"] == "p2"
    with pytest.raises(LookupError):
        find_row(ROWS, "nope")


PREP_JSON = json.dumps({
    "situation": "R1 已过，主动权在我方，R2 定生死",
    "strategy": ["用 A1 的 pipeline 案例打头", "系统设计先问量级", "p3", "p4", "p5",
                 "第六条应被配额截断"],
    "qa_prep": [{"q": "为什么离开上家", "a": "标准 30 秒版本，按口径"},
                {"q": "q2", "a": "a2"}, {"q": "q3", "a": "a3"},
                {"q": "第四问应被配额截断", "a": "x"}],
    "asks": ["团队现在最痛的技术问题"],
    "watchouts": ["tenure question 还在 needs_work——别被带进去"],
}, ensure_ascii=False)


def test_build_brief_staff_sections(cfg):
    """LLM 参谋路径：全量战况进 prompt；产出关键打法置顶、配额硬截断、过金标硬检查。"""
    from joblander import company as cf
    (cfg.workspace_dir / "03-materials" / "achievement-bank.md").write_text(
        "## Alpha Corp\n\n### A1. pipeline 战绩\n- built ml pipeline\n", encoding="utf-8")
    cf.timeline_add(cfg, "Acme AI", kind="interview", title="R1 电面",
                    content_md="聊了 pipeline，对方追问 K8s")
    cf.save_meta(cfg, "Acme AI", {"resume_variant": "定制 v2",
                                  "assessment": {"jd_match": {"score": 4}}})
    ddir = cfg.workspace_dir / "14-dossiers"
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "Acme-AI.json").write_text(json.dumps({
        "card": ["扩张期招人"], "summary_md": "**这家公司是谁** x",
        "risks": ["有裁员史"], "gaps": ["确认面试轮数"]}, ensure_ascii=False),
        encoding="utf-8")

    llm = MockLLM([PREP_JSON])
    out, text = build_brief(cfg, llm, "Acme", round_note="watch the tenure question",
                            round_type="tech")
    assert out.exists()
    prompt = llm.calls[0]["prompt"]
    for piece in ("R1 电面", "定制 v2", "扩张期招人", "确认面试轮数",
                  "jd_match", "A1. pipeline", "技术轮"):
        assert piece in prompt, f"输入缺：{piece}"
    for anchor in ("参谋 Brief", "## 局面", "## 接下来的打法", "## 预判问答",
                   "## 本场必问", "## 易翻车点", "watch the tenure question",
                   "红线口径 → /system", "needs_work：P1"):
        assert anchor in text, f"缺 section：{anchor}"
    assert "第六条应被配额截断" not in text        # strategy 配额 5 条硬截断
    assert "第四问应被配额截断" not in text        # qa_prep 配额 3 条硬截断
    assert llm.calls[0]["effort"] == "high"        # 深度靠 reasoning，不靠放宽篇幅
    from evals.brief_eval import hard_checks as brief_hard
    bank = (cfg.workspace_dir / "03-materials" / "achievement-bank.md").read_text()
    assert brief_hard(text, bank) == []            # 产出必须过自家评测的硬检查
    tl = [e for e in cf.local_entries(cfg, "Acme AI")
          if (e.get("title") or "").startswith("参谋 Brief")]
    assert len(tl) == 1 and tl[0]["title"] == "参谋 Brief：技术轮"   # brief 落时间线
    assert not tl[0]["content_md"].startswith("# ")                # 不重复 H1 头
    build_brief(cfg, MockLLM([PREP_JSON]), "Acme", round_type="hm")
    tl2 = [e for e in cf.local_entries(cfg, "Acme AI")
           if (e.get("title") or "").startswith("参谋 Brief")]
    assert len(tl2) == 1 and "Hiring Manager" in tl2[0]["title"]   # 重生成 upsert 不堆条


SCRIBE_JSON = json.dumps({
    "field_diffs": {"Status": "Interview Completed", "Highlight": "R2 done, waiting result"},
    "body_entry": "### 2026-08-07 R2 面试\n- 录入：谈了 ProjectX 架构\n- 复盘：数字出口 ok",
    "playbook_updates": [{"id": "P2", "outcome": "hit", "note": "said the number"}],
    "confidence_notes": [],
}, ensure_ascii=False)


def test_run_scribe_builds_proposal_with_sentinel(cfg):
    llm = MockLLM([SCRIBE_JSON])
    proposal = run_scribe(cfg, llm, "transcript text here", ROWS[0], today="2026-08-07")
    assert proposal["field_diffs"]["Status"] == "Interview Completed"
    assert proposal["approved"] is None                      # 提案语义：等人批
    assert "codename" in proposal["sentinel"]                # internal 命中 → 标注（WARN）
    assert "WARN" in proposal["sentinel"]
    assert llm.calls[0]["json_mode"] is True
    assert "tracker 当前行" in llm.calls[0]["prompt"]


def test_run_scribe_strips_code_fences(cfg):
    llm = MockLLM(["```json\n" + SCRIBE_JSON + "\n```"])
    proposal = run_scribe(cfg, llm, "t", ROWS[0])
    assert proposal["field_diffs"]["Status"] == "Interview Completed"


def test_mock_llm_exhaustion():
    llm = MockLLM([])
    with pytest.raises(LLMError):
        llm.generate("hi")


def test_build_prop_payloads():
    assert build_prop("status", "Applied") == {"status": {"name": "Applied"}}
    assert build_prop("date", None) == {"date": None}
    assert build_prop("rich_text", "hi")["rich_text"][0]["text"]["content"] == "hi"
    with pytest.raises(ValueError):
        build_prop("files", "x")


def test_markdown_to_blocks():
    blocks = markdown_to_blocks("### 2026-08-07 事件\n- 要点一\n正文段落\n\n")
    assert [b["type"] for b in blocks] == ["heading_3", "bulleted_list_item", "paragraph"]
    assert blocks[0]["heading_3"]["rich_text"][0]["text"]["content"] == "2026-08-07 事件"


def test_build_brief_fallback_when_llm_down(cfg):
    """参谋掉线：降级模板骨架照出——轮次打法/必问在，同样不罗列，带降级标记。"""
    (cfg.workspace_dir / "03-materials" / "achievement-bank.md").write_text(
        "## Alpha Corp — engineer 战绩\n- built engineer ml pipeline\n", encoding="utf-8")
    _, text = build_brief(cfg, MockLLM([]), "Acme", round_type="tech")
    assert "降级版" in text and "技术轮·通用模板" in text
    assert "团队技术栈" in text                       # tech 模板必问
    assert "STAR 弹药索引" not in text                # 降级版同样不罗列（10 分钟金标）
    assert "红线口径 → /system" in text               # 只指路不复印
    _, generic = build_brief(cfg, MockLLM([]), "Acme")
    assert "本轮打法" not in generic and "band/档位" in generic
    _, neg = build_brief(cfg, MockLLM([]), "Acme", round_type="negotiation")
    assert "谈判轮" in neg and "答复截止时间" in neg


def test_guess_round():
    from joblander.prep import guess_round
    assert guess_round("Tech Interview with Acme") == "tech"
    assert guess_round("HR Screening Call") == "screening"
    assert guess_round("Chat with Hiring Manager") == "hm"
    assert guess_round("Offer discussion") == "negotiation"
    assert guess_round("Acme AI 二面") == ""            # 猜不中回通用


def test_brief_eval_hard_checks():
    """用户金标回归：超长/整段罗列/问答超量/空话/幻觉弹药编号，逐项能抓；好例通过。"""
    from evals.brief_eval import hard_checks
    bank = "### A1. x\n### T2. y\n"
    bad = ("# brief\n## 口径卡（原样）\n- x\n## 弹药点名\n- A1\n"
           + "".join(f"- **Q：q{i}**\n" for i in range(7))
           + "保持自信。引用 A9 的战绩。\n" + "废" * 4600)
    v = hard_checks(bad, bank)
    joined = " ".join(v)
    assert "超 10 分钟预算" in joined and "口径卡" in joined and "弹药点名" in joined
    assert "预判问答 7 条" in joined and "模板空话" in joined
    assert "A9" in joined                          # 幻觉编号（A 前缀在库、A9 不在）
    good = ("# brief\n## ⚡ 关键打法\n1. 用 A1 的数字打头，见 R1 复盘\n"
            "## 预判问答\n- **Q：q**\n  → a（P0 中位 0.8 天）\n")
    assert hard_checks(good, bank) == []           # R1/P0 前缀不在库，不误伤
