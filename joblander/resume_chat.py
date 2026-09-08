"""简历教练对话 —— 定制简历的对话式入口（提取 → 定点入库提案 → 确认落库）。

用户在公司页和「教练」对话：丢进来的信息被分类为
- facts：弹药库事实 → 定点归档到具体条目（### A1/T2/J4…）或新建条目——库保持策展结构，
  不再按日期堆「补充素材」尾巴
- opinions：本公司定制意见 → 并入 meta.resume.feedback（持久累积，不是产一版就清空）——
  定制官每次生成都从这份完整意见集合重新出版，不是只吃「最新一条」
- reply：教练的回话（答疑/追问/确认收到什么）

入库走轻提案制（与 J1「AI 写入一律走提案制」同构）：教练亮出归档计划（target + bullets），
用户在对话里点「确认入库」才动库。手术纪律：只追加不删改；⚠️/使用注意段绝不触碰。
对话史落 <company>/resume/chat.json。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from joblander.tz import LOCAL_TZ as SGT   # 单一来源，JOBLANDER_TZ 可覆盖

CHAT_SYSTEM = """你是候选人的简历教练兼弹药官。对话目标：把用户丢进来的任何信息接住、
归类、归档，为下一版定制简历补充弹药。

输入：弹药库全文（唯一事实来源）、最近一次招聘方评审建议补充的信息（如有）、
对话历史、用户本条消息。

把用户消息拆解后输出严格 JSON：
{"reply": "教练回话——确认收到什么、归到哪、还缺什么就追问一条；答疑也在这里。短，说人话",
 "generate": false,
 "facts": [{"target": "归档目标条目编号，如 A1/T2/J4——必须是弹药库里真实存在的条目；
             实在没有归属才用 new", "new_section": "target=new 时：归入哪个 ## 段（如公司名段）",
            "new_title": "target=new 时：新条目标题（如 T8. xxx）",
            "bullets": ["以「- 」开头的事实句——保留用户的数字与口径，转成库内简洁风格，不放大"]}],
 "opinions": ["用户对本公司简历定制的意见/指令（非事实），逐条原意保留"]}

纪律：
- generate 只在用户**明确要求现在出版**时为 true（「出一版」「生成新版」「重新出」类祈使）；
  补料、提意见、提问、讨论一律 false——出版是大动作，宁可让用户多说一句，不许抢跑
- 收到事实/意见而 generate=false 时，reply 末尾带一句引导：
  「都记下了——说『出一版』或点 ⚙ 即出新版」（引导确认，不自作主张）
- 事实与意见分清：「QPS 3000」是 fact；「把 agent 一节放最前」是 opinion；提问只回 reply
- target 优先归入已有条目——先在弹药库里找最贴的 ###，找不到才 new
- 数字逐字保留，禁止编造、放大或补全用户没说的；含糊处在 reply 里追问而不是脑补
- 用户消息与事实无关（闲聊/提问）时 facts/opinions 给空数组，reply 正常答
- ⚠️ 开头或「使用注意」类条目永远不是归档目标"""


def chat_path(cfg, company: str):
    from joblander.resume_agent import resume_dir
    return resume_dir(cfg, company) / "chat.json"


def load_chat(cfg, company: str) -> list[dict[str, Any]]:
    p = chat_path(cfg, company)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _save_chat(cfg, company: str, turns: list[dict[str, Any]]) -> None:
    p = chat_path(cfg, company)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")


def _entry_ids(bank: str) -> list[str]:
    return re.findall(r"^### ([A-Z]+\d+)\.", bank, re.M)


def apply_facts(cfg, facts: list[dict[str, Any]]) -> list[str]:
    """定点手术：bullets 追加进目标 ### 条目末尾（或新建条目）。只追加不删改；
    ⚠️/使用注意段拒收。返回人读得懂的变更清单。"""
    from joblander.arsenal import bank_path

    p = bank_path(cfg)
    bank = p.read_text(encoding="utf-8")
    changed: list[str] = []
    for f in facts:
        bullets = [b if b.startswith("- ") else f"- {b}" for b in f.get("bullets") or []]
        if not bullets:
            continue
        target = (f.get("target") or "").strip().rstrip(".")
        if target and target.lower() != "new":
            m = re.search(rf"^### {re.escape(target)}\..*?(?=^### |^## |\Z)", bank, re.M | re.S)
            if m and "⚠️" not in bank[m.start():bank.find("\n", m.start())] :
                block = m.group(0)
                bank = bank[:m.start()] + block.rstrip() + "\n" + "\n".join(bullets) + "\n\n" + bank[m.end():]
                changed.append(f"{target} 追加 {len(bullets)} 条")
                continue
        sec = (f.get("new_section") or "").strip()
        title = (f.get("new_title") or "未归类补充").strip()
        if "⚠️" in title or "使用注意" in title:
            continue
        sm = re.search(rf"^## {re.escape(sec)}.*?(?=^## |\Z)", bank, re.M | re.S) if sec else None
        entry = f"### {title}\n\n" + "\n".join(bullets) + "\n"
        if sm:
            bank = bank[:sm.end()].rstrip() + "\n\n" + entry + "\n" + bank[sm.end():]
        else:   # 找不到归属段：挂在「素材使用注意」之前，规则永远垫底
            cut = bank.find("## ⚠️ 素材使用注意")
            bank = (bank[:cut].rstrip() + "\n\n" + f"## 补充素材\n\n{entry}\n" + bank[cut:]) \
                if cut > 0 else bank.rstrip() + "\n\n" + entry
        changed.append(f"新条目「{title}」{len(bullets)} 条")
    if changed:
        p.write_text(bank, encoding="utf-8")
    return changed


def talk(cfg, llm, company: str, message: str,
         store_opinions: bool = True) -> dict[str, Any]:
    """一轮对话：分类提取 → 存对话史（含待确认归档计划）→ 返回给 UI。
    opinions 无论 generate 与否都并入 meta.resume.feedback（持久累积、去重）——
    generate 意图位只决定这轮要不要顺手触发生成，不影响意见要不要记账。"""
    from joblander.arsenal import bank_path
    from joblander.resume_agent import resume_state
    from joblander.scribe import _strip_fences

    bank = bank_path(cfg).read_text(encoding="utf-8") if bank_path(cfg).exists() else ""
    state = resume_state(cfg, company)
    cur = next((x for x in state.get("versions") or []
                if x.get("file") == state.get("current")), {})
    needs = (cur.get("eval") or {}).get("needs_user") or []
    turns = load_chat(cfg, company)
    hist = "\n".join(f"[{t['role']}] {t['text'][:300]}" for t in turns[-8:])

    now = datetime.now(SGT).strftime("%Y-%m-%d %H:%M")
    turns.append({"role": "user", "text": message, "at": now})
    _save_chat(cfg, company, turns)               # 用户输入先落盘——LLM 挂了消息也不丢

    try:
        out = json.loads(_strip_fences(llm.generate(
            f"【弹药库全文】\n{bank[:60000]}\n\n"
            f"【最近评审建议补充】\n{json.dumps(needs, ensure_ascii=False) or '（无）'}\n\n"
            f"【对话历史（旧→新）】\n{hist or '（首轮）'}\n\n"
            f"【用户本条消息】\n{message}",
            system=CHAT_SYSTEM, json_mode=True)))
    except Exception as e:                        # 教练掉线也留回执，历史完整可重试
        out = {"reply": f"（教练这轮没接上：{str(e)[:120]}——你的消息我已记下，重发一遍即可拿归档计划）",
               "facts": [], "opinions": []}

    known = set(_entry_ids(bank))
    facts = [f for f in out.get("facts") or []
             if (f.get("target") in known) or str(f.get("target", "")).lower() == "new"]
    plan_id = uuid.uuid4().hex[:8] if facts else ""
    turns.append({"role": "coach", "text": out.get("reply") or "收到。", "at": now,
                  "plan_id": plan_id, "facts": facts,
                  "opinions": out.get("opinions") or [], "applied": False})
    _save_chat(cfg, company, turns)

    gen = bool(out.get("generate"))
    if out.get("opinions") and store_opinions:
        from joblander.company import save_meta
        fb = state.setdefault("feedback", [])
        for op in out["opinions"]:
            op = str(op).strip()
            if op and op not in fb:
                fb.append(op)
        save_meta(cfg, company, {"resume": state})
    return {"reply": turns[-1]["text"], "plan_id": plan_id, "facts": facts,
            "opinions": out.get("opinions") or [], "generate": gen}


def apply_plan(cfg, company: str, plan_id: str) -> dict[str, Any]:
    """确认入库：按 plan_id 找到对话里的归档计划，动库并标记 applied。"""
    from joblander.eventlog import EventLog

    turns = load_chat(cfg, company)
    turn = next((t for t in turns if t.get("plan_id") == plan_id), None)
    if turn is None:
        raise ValueError("归档计划不存在——可能已过期")
    if turn.get("applied"):
        return {"changed": [], "note": "已入过库"}
    changed = apply_facts(cfg, turn.get("facts") or [])
    turn["applied"] = True
    _save_chat(cfg, company, turns)
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "arsenal.chat_merged", "agent:resume_coach",
        {"company": company, "changed": changed})
    return {"changed": changed}
