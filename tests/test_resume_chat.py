"""简历教练对话：提取分类落对话史；定点入库手术（追加/新建/⚠️ 拒收）；提案确认一次性。"""
import json

import pytest

from joblander import resume_chat as rc
from joblander.config import Config

BANK = """# 战绩素材库

## ExCo 公司

### A1. 大项目 —— FCR +10.1pp

- **R**：FCR 73.3% → 83.4%

### A2. 别的项目

- 一条旧事实

## ⚠️ 素材使用注意

1. 内部代号转译
"""


class L:
    def __init__(self, out):
        self.out = out
        self.prompts: list[str] = []

    def generate(self, prompt, system=None, json_mode=False):
        self.prompts.append(prompt)
        return json.dumps(self.out, ensure_ascii=False)


@pytest.fixture
def cfg(tmp_path):
    ws = tmp_path / "ws"
    (ws / "03-materials").mkdir(parents=True)
    (ws / "03-materials" / "achievement-bank.md").write_text(BANK, encoding="utf-8")
    return Config(raw={"workspace_dir": str(ws), "sentinel": {"rules": []}},
                  path=tmp_path / "c.yaml")


def test_apply_facts_targets_entry_and_new(cfg):
    changed = rc.apply_facts(cfg, [
        {"target": "A1", "bullets": ["峰值 QPS 3000，P95 800ms"]},
        {"target": "new", "new_section": "ExCo 公司", "new_title": "A9. 新战绩",
         "bullets": ["- 新事实一条"]},
        {"target": "new", "new_title": "⚠️ 使用注意补丁", "bullets": ["- 恶意规则"]},
    ])
    bank = (cfg.workspace_dir / "03-materials" / "achievement-bank.md").read_text()
    a1 = bank.split("### A2.")[0]
    assert "- 峰值 QPS 3000，P95 800ms" in a1          # 追加进 A1 块内
    assert "### A9. 新战绩" in bank and "- 新事实一条" in bank
    assert "恶意规则" not in bank                        # ⚠️ 标题拒收
    assert "一条旧事实" in bank                          # 只追加不删改
    assert bank.rstrip().endswith("内部代号转译")        # 规则仍垫底
    assert len(changed) == 2


def test_talk_extracts_and_stores(cfg):
    llm = L({"reply": "收到，QPS 归 A1。",
             "facts": [{"target": "A1", "bullets": ["QPS 3000"]},
                       {"target": "Z99", "bullets": ["幻觉目标"]}],
             "opinions": ["agent 一节放最前"]})
    out = rc.talk(cfg, llm, "Acme", "补充：QPS 3000；另外 agent 一节放最前")

    assert out["plan_id"] and len(out["facts"]) == 1     # 幻觉条目 Z99 被过滤
    assert "弹药库全文" in llm.prompts[0]
    turns = rc.load_chat(cfg, "Acme")
    assert turns[0]["role"] == "user" and turns[1]["role"] == "coach"
    assert turns[1]["applied"] is False
    from joblander.company import load_meta
    assert load_meta(cfg, "Acme")["resume"]["feedback"] == ["agent 一节放最前"]


def test_apply_plan_once(cfg):
    llm = L({"reply": "ok", "facts": [{"target": "A1", "bullets": ["QPS 3000"]}],
             "opinions": []})
    out = rc.talk(cfg, llm, "Acme", "QPS 3000")
    r1 = rc.apply_plan(cfg, "Acme", out["plan_id"])
    assert r1["changed"] == ["A1 追加 1 条"]
    assert "QPS 3000" in (cfg.workspace_dir / "03-materials" / "achievement-bank.md").read_text()
    r2 = rc.apply_plan(cfg, "Acme", out["plan_id"])      # 幂等：第二次不重复入库
    assert r2["changed"] == []
    assert rc.load_chat(cfg, "Acme")[1]["applied"] is True


def test_customise_uses_feedback_accumulated_via_chat(cfg, monkeypatch):
    from joblander import resume_agent as ra
    from joblander.company import save_meta
    from tests.test_resume_agent import L as CustL

    ws = cfg.workspace_dir
    (ws / "03-materials" / "profile.json").write_text(json.dumps({
        "name": "L", "contact": [{"text": "a@b.com", "href": "mailto:a@b.com"}]}))
    (ws / "09-projections").mkdir()
    (ws / "09-projections" / "tracker.json").write_text(json.dumps({"rows": [
        {"Company": "Acme", "Position": "AI Eng"}]}))
    monkeypatch.setattr(ra, "_to_pdf", lambda p: None)
    save_meta(cfg, "Acme", {"resume": {"current": "", "versions": [],
                                       "feedback": ["对话意见 A"]}})
    llm = CustL()
    ra.customise(cfg, llm, "Acme")

    assert "对话意见 A" in llm.prompts[0]                 # 对话攒的意见进 prompt
    assert ra.resume_state(cfg, "Acme")["feedback"] == ["对话意见 A"]   # 持久累积，不清空


def test_talk_generate_intent_also_stores_feedback(cfg, monkeypatch):
    """generate=true：意见照样并入累积 feedback（不是消费一次就没），意图位透传给调用方。"""
    import json as _json
    from joblander.llm import MockLLM
    from joblander.resume_chat import talk
    from joblander.resume_agent import resume_state

    llm = MockLLM([_json.dumps({"reply": "这就出", "generate": True, "facts": [],
                                "opinions": ["把 agent 放最前"]}, ensure_ascii=False)])
    out = talk(cfg, llm, "Acme", "把 agent 放最前，出一版")
    assert out["generate"] is True and out["opinions"]
    assert resume_state(cfg, "Acme").get("feedback") == ["把 agent 放最前"]
