"""Resume Eval：硬检查（量化密度/Sentinel/联系方式）+ 盲评→教练两步 + 版本回写。"""
import json

import pytest

from joblander.config import Config

RECRUITER_JSON = json.dumps({
    "screen": {"pass": "yes", "flags": ["最近一段任期短"]},
    "hm": {"read": "borderline",
           "jd_fit": [{"req": "LLM 应用", "evidence": "FCR +10.1pp", "grade": "strong"}],
           "probes": ["FCR 归因怎么建立？"],
           "weak_bullets": [{"quote": "improving conversion", "why": "无数字"}]},
    "verdict": {"interview": "yes", "one_line": "过线但需补证据",
                "top_fixes": ["给 chatbot 条目补量化"]}}, ensure_ascii=False)

COACH_JSON = json.dumps({
    "agent_fixable": ["FCR 战绩前置到第一条"],
    "needs_user": [{"q": "chatbot 的 conversion 增幅是多少？", "why": "弱条目无数字"}]},
    ensure_ascii=False)


class L:
    def __init__(self):
        self.calls: list[dict] = []
        self.responses = [RECRUITER_JSON, COACH_JSON]

    def generate(self, prompt, system=None, json_mode=False):
        self.calls.append({"prompt": prompt, "system": system})
        return self.responses.pop(0)


@pytest.fixture
def cfg(tmp_path):
    ws = tmp_path / "ws"
    (ws / "03-materials").mkdir(parents=True)
    (ws / "03-materials" / "resume.html").write_text(
        "<!DOCTYPE html><html><body>a@b.com<ul>"
        + "<li>Lifted FCR from 73.3% to 83.4% with a 164-case regression suite in production</li>"
        + "<li>Built a multi-agent chatbot improving conversion and seller satisfaction rates</li>"
        + "</ul></body></html>", encoding="utf-8")
    (ws / "03-materials" / "achievement-bank.md").write_text(
        "# 弹药库\n## ExCo\n- FCR +10.1pp\n", encoding="utf-8")
    return Config(raw={"workspace_dir": str(ws), "sentinel": {"rules": []}},
                  path=tmp_path / "c.yaml")


def test_hard_checks_quant_density_and_contact(cfg):
    from evals.resume_eval import hard_checks
    html = ("<html><body><ul>"
            "<li>负责了很多重要的系统改进工作，推动了显著的业务价值提升与增长</li>"
            "<li>主导团队完成关键项目落地，广受好评并获得管理层认可与表彰嘉奖</li>"
            "</ul></body></html>")
    v = hard_checks(cfg, html)
    assert any("量化密度低" in x for x in v)
    assert any("联系方式" in x for x in v)
    ok = ("<html><body>a@b.com<ul>"
          "<li>把首次解决率从 73.3% 提到 83.4%，灰度三波上线覆盖全部市场流量</li>"
          "</ul></body></html>")
    assert hard_checks(cfg, ok) == []


def test_run_blind_review_then_coach_and_writeback(cfg, monkeypatch):
    from joblander import resume_agent as ra
    from joblander.company import load_meta, save_meta
    import evals.resume_eval as re_mod

    d = ra.resume_dir(cfg, "Acme")
    d.mkdir(parents=True, exist_ok=True)
    (d / "resume-v1.html").write_text(
        "<html><body>a@b.com<li>FCR 73.3% → 83.4% 生产三波灰度上线覆盖全市场</li></body></html>",
        encoding="utf-8")
    save_meta(cfg, "Acme", {"resume": {"current": "resume-v1",
                                       "versions": [{"v": 1, "file": "resume-v1"}]}})
    llm = L()
    monkeypatch.setattr(re_mod, "hard_checks", lambda c, h: [])
    monkeypatch.setattr("joblander.llm.from_config", lambda c, tier="pro": llm)

    out = re_mod.run(cfg, "Acme")

    assert [c["prompt"] for c in llm.calls]
    assert "弹药库" not in llm.calls[0]["prompt"]          # 盲评信息集：招聘方看不到弹药库
    assert "FCR +10.1pp" in llm.calls[1]["prompt"]         # 教练信息集：持弹药库分拣
    ev = (load_meta(cfg, "Acme")["resume"]["versions"][0]).get("eval")
    assert ev and ev["interview"] == "yes" and ev["agent_fixable"]
    assert ev["needs_user"][0]["q"].startswith("chatbot")
    assert (cfg.workspace_dir / "16-audits" / ev["report"]).exists()
    assert out["label"] == "resume-v1"
    asked = load_meta(cfg, "Acme")["resume"].get("asked_user") or []
    assert [a["q"] for a in asked] == ["chatbot 的 conversion 增幅是多少？"]   # 问过即记账


def test_run_never_reasks_unanswered_questions(cfg, monkeypatch):
    """已问未答的补料问题不重提：prompt 带清单、代码侧兜底过滤、报告注明省略条数。"""
    from joblander import resume_agent as ra
    from joblander.company import load_meta, save_meta
    import evals.resume_eval as re_mod

    d = ra.resume_dir(cfg, "Acme")
    d.mkdir(parents=True, exist_ok=True)
    (d / "resume-v2.html").write_text("<html><body>a@b.com</body></html>", encoding="utf-8")
    save_meta(cfg, "Acme", {"resume": {
        "current": "resume-v2", "versions": [{"v": 2, "file": "resume-v2"}],
        "asked_user": [{"q": "chatbot 的 conversion 增幅是多少？",
                        "file": "resume-v1", "at": "2026-08-09"}]}})
    llm = L()                                   # 教练 mock 仍返回同一条问题（模型漏守）
    monkeypatch.setattr(re_mod, "hard_checks", lambda c, h: [])
    monkeypatch.setattr("joblander.llm.from_config", lambda c, tier="pro": llm)

    out = re_mod.run(cfg, "Acme")
    assert "已问过用户的补料问题" in llm.calls[1]["prompt"]       # 清单进教练 prompt
    assert out["coach"]["needs_user"] == []                       # 兜底过滤：不重提
    meta = load_meta(cfg, "Acme")["resume"]
    assert meta["versions"][0]["eval"]["needs_user"] == []
    assert len(meta.get("asked_user") or []) == 1                 # 记账不重复膨胀
    report = (cfg.workspace_dir / "16-audits" / meta["versions"][0]["eval"]["report"]).read_text()
    assert "1 条此前问过、未回应——不再重复提" in report


def test_run_falls_back_to_master_without_versions(cfg, monkeypatch):
    import evals.resume_eval as re_mod
    llm = L()
    monkeypatch.setattr("joblander.llm.from_config", lambda c, tier="pro": llm)
    out = re_mod.run(cfg, "NoCustom")
    assert out["label"] == "母版"
    assert "83.4" in llm.calls[0]["prompt"]                # 评的是母版内容
