"""ResumeCustomiserAgent —— 弹药库 × 公司 JD × 累积修改意见 → 定制简历结构化内容，
渲染进固定 HTML 骨架（版式代码化，定制官只出内容，不产 HTML、不参考母版）。

事实纪律：一切战绩数字只能来自弹药库（唯一事实来源）；姓名/联系方式固定渲染，
定制官管不着——身份事实没有被编造的必要，也不该有被编造的风险。
产出先过 Sentinel（对外受众，拦截即拒绝落盘）——绩效评级、真实薪资永不上简历。

单轮：一次点击 = 一次生成，不再有 Agent↔Evaluator 自动多轮改稿
（2026-08-13 拆除：真实数据里从没真正收敛过，只是把每次点击的耗时/成本翻好几倍，
还总多出一版用户没要的中间版本）。改进靠用户反馈：教练对话把意见并进
meta.resume.feedback（持久累积、不是产一版就清空），下次生成永远带着全部历史意见，
从弹药库+JD+意见集合整份重新生成——不基于上一版 HTML 增量编辑，避免连续编辑
造成的版式/口径漂移。招聘方视角评审（evals/resume_eval）改成按钮手动触发。

公司情报（2026-08-14 补）：JD 原文经常不完整或读不出岗位真实性质——弹药库+JD
两路输入曾漏掉过时间线电话纪要里的关键定位信号（该公司实际看重 applied research，
JD 文本只字未提）。定制官额外拿到该公司的尽调摘要（14-dossiers/<slug>.json 的
summary_md）与时间线里「通话」类条目的摘录（复用 prep.py 已有的 _dossier/
_timeline_digest，控制在小预算内，不吃 prev_html/母版砍掉的那部分空间）——
这段情报只用来判断"强调什么、砍什么"，不是简历事实来源，红线纪律见下方。

版本化：18-companies/<slug>/resume/resume-v{n}.html/.pdf；meta.resume 记当前版本、
每版定制说明与来源——哪家投了哪版，一查便知。
"""

from __future__ import annotations

import html as html_mod
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from joblander.tz import LOCAL_TZ as SGT   # 单一来源，JOBLANDER_TZ 可覆盖

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

RESUME_SYSTEM = """你是候选人的简历定制官——根据弹药库（战绩唯一事实来源）和目标公司 JD，
决定一份定制简历该展示什么、怎么措辞、怎么取舍。你只产出结构化内容，不产出排版——
姓名与联系方式由系统固定渲染，不在你的输出范围内，你不知道也不需要知道。

输入：弹药库全文（含【素材使用注意】纪律）、目标公司与 JD、
（有时）该公司情报——尽调摘要 + 时间线通话/笔记摘录，只用来判断定位角度，
不是事实来源、绝不能从这里搬事实进简历、（有累积意见时）修改意见集合——逐条精确执行。

输出严格 JSON：
{"tagline": "姓名下方一行定位语，对准 JD 的角色关键词",
 "summary": ["Summary 段落一", "段落二（可选，没有就一段）"],
 "experience": [{"company": "公司/项目名", "position": "对外职位头衔（不是弹药库内部团队/角色标注）",
                 "when": "地点 · 起止时间", "note": "一行说明（如任期结束原因），没有给空字符串",
                 "bullets": ["战绩句，带数字优先，关键数字/短语可用 <strong> 包起来"]}],
 "skills": [{"label": "技能分类名", "value": "该类下的技能/工具，逗号分隔"}],
 "education": [{"degree": "学位与专业", "institution": "学校", "when": "起止年份",
                "sub": "一行补充（导师/奖学金/发表），没有给空字符串"}],
 "publications": ["一条发表记录的完整文本；版面紧张时这段整体可砍，给空数组"],
 "service": "学术服务一行总结，没有给空字符串",
 "changes": ["3-6 条：本版具体做了哪些定制——选了哪些经历前置及为什么对准 JD、
              删减/压缩了什么、Summary 怎么改的、（有意见时）意见是怎么执行的；
              如果某条取舍是被该公司情报影响的（不是 JD 原文字面写的），说明依据，
              比如「XX 通话提到该岗位看重 applied research，故保留 Publications」"]}

纪律：
- 事实纪律（红线）：数字与事实只能来自弹药库或修改意见集合里用户主动给出的（视为已授权弹药），
  除此之外禁止编造或放大；【素材使用注意】必须逐条遵守
  （内部系统代号转译成通用描述；不提绩效评级；不写薪资数字；不贬损前雇主）
- 若【素材使用注意】里出现"不要透露绝对业务量"一类规则：指的是公司内部运营规模数字
  （如日活、ticket/工单总量、公司整体收入这类跟候选人个人产出无关的规模指标），
  不包括候选人自己的归因结果数字——FCR、CSAT、GMV 贡献额这类"个人绩效表述"该注意里
  通常会明确说可以写，必须保留，不能因为怕踩线而连这些一起模糊化或删掉
- 该公司情报（尽调摘要/时间线摘录）只用来判断定位角度和取舍——哪块背景该强调、
  哪块该压缩、Publications 这类可选段留不留；里面的公司背景、第三方推断、薪酬信号
  绝不能当成候选人自己的战绩或经历写进简历，弹药库之外的"事实"一律不算数
- 战绩取舍：与 JD + 该公司情报共同指向的方向最相关的经历/条目前置、展开；
  无关的压缩或删除，版面紧张时可以把弱相关的早期经历合并成一条「Earlier Experience」——
  版面没紧张就不要为了"看起来精炼"硬砍，取舍要有依据，不是为砍而砍
- 量化优先：带数字/基线的弹药前置；弹药库没数字的条目不得用 improving/raising 类空话撑场——
  保守表述或压缩，把版面让给有证据链的战绩
- Summary/tagline 只声称有战绩条目支撑的能力——技能清单里的词不自动等于亮点
- position 填候选人对外用的职位头衔，不是弹药库段落元信息里的内部团队/角色标注
  （如「团队：AI & Data Service | Chatbot DS」这类行是组织上下文，不是头衔，绝不能
  照抄或展开成 position）；弹药库没给出明确对外头衔时，按候选人整体定位
  （AI Engineer / ML Engineer 一类通用行业头衔）拟一个，不要用内部缩写代替
- experience 顺序与数量、是否合并早期经历、skills 分类与顺序、education 的 sub 行、
  publications 是否保留——都由你根据 JD 和版面取舍决定，不必照抄弹药库原有结构
- 修改意见集合：逐条精确执行；没有冲突就都要落实，冲突以最新一条为准
- bullets/summary 里除 <strong> 包关键数字、<a href="..."> 包引用链接外，不要用其他标签；
  company/position/when/degree/institution/skill label 是事实短语，纯文本，不要加标签"""


def resume_dir(cfg, company: str) -> Path:
    from joblander.company import company_dir
    return company_dir(cfg, company, create=True) / "resume"


def resume_state(cfg, company: str) -> dict[str, Any]:
    from joblander.company import load_meta
    return load_meta(cfg, company).get("resume") or {"current": "", "versions": [], "feedback": []}


def _find_chrome() -> str:
    """按平台找 Chrome/Chromium/Edge。原先只认 macOS 的绝对路径 + `chromium` 一个名字，
    Linux 上常见的 google-chrome / chromium-browser 与 Windows 全都落空——PDF 静默不出，
    用户只拿到 HTML 且没有任何提示。可用 JOBLANDER_CHROME 显式指定。"""
    import os
    explicit = os.environ.get("JOBLANDER_CHROME")
    if explicit and Path(explicit).exists():
        return explicit
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    for p in (CHROME,                                            # macOS
              "/Applications/Chromium.app/Contents/MacOS/Chromium",
              "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if Path(p).exists():
            return p
    return ""


def _to_pdf(html_path: Path) -> Path | None:
    """Chrome headless 转 PDF；找不到浏览器就只出 HTML（不阻塞出版）。"""
    pdf = html_path.with_suffix(".pdf")
    chrome = _find_chrome()
    if not chrome:
        return None
    try:
        subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf}", f"file://{html_path}"],
                       capture_output=True, timeout=60, check=True)
        return pdf if pdf.exists() else None
    except Exception:
        return None


def _load_profile(cfg) -> dict[str, Any]:
    p = cfg.workspace_dir / "03-materials" / "profile.json"
    if not p.exists():
        raise ValueError("身份信息不存在——先建 03-materials/profile.json"
                          "（姓名 + 联系方式，定制官不碰这段，系统固定渲染）")
    return json.loads(p.read_text(encoding="utf-8"))


def _esc(v: Any) -> str:
    return html_mod.escape(str(v or ""), quote=False)


_RICH_TOKEN = re.compile(
    r"&lt;(?P<close>/?)(?P<tag>strong|em|b|i)&gt;"      # 允许的纯标签
    r"|&lt;a href=&quot;(?P<href>.*?)&quot;&gt;"        # 链接开标签（URL 事后校验）
    r"|(?P<enda>&lt;/a&gt;)")


def _rich(v: Any) -> str:
    """允许 LLM 在正文里用一小组内联标签，其余一律转义。

    这些字段（bullets/summary/note/sub/publications）的输入含抓来的 JD 与尽调摘要，
    prompt 注入可以让模型把 `<img src=x onerror=...>` 写进简历；产物又由 /files
    在浏览器里打开。先整体转义、再把白名单标签放回来——注入进来的东西只会以
    字面文本出现在简历上（显眼、可发现），而不是被执行。

    链接的 URL 先解转义再校验协议：带 query 的外链（?a=1&b=2）转义后含 &amp;，
    早期用字符类匹配会整条漏掉——开标签留在转义态、闭标签却被还原，产出一个
    没有开头的孤立 </a>，链接同时失效。闭标签因此改为只在真开过时才还原。"""
    s = html_mod.escape(str(v or ""), quote=True)
    depth = 0

    def _back(m: re.Match) -> str:
        nonlocal depth
        if m.group("tag"):
            return f"<{m.group('close')}{m.group('tag')}>"
        if m.group("href") is not None:
            url = html_mod.unescape(m.group("href"))
            if url.lower().startswith(("http://", "https://")) and '"' not in url:
                depth += 1
                return f'<a href="{html_mod.escape(url, quote=True)}">'
            return m.group(0)               # 非 http(s)（含 javascript:）保持转义
        if depth > 0:                       # 只闭合真开过的，不留孤立 </a>
            depth -= 1
            return "</a>"
        return m.group(0)

    return _RICH_TOKEN.sub(_back, s)


def _contact_html(contact: list[dict]) -> str:
    parts = []
    for c in contact or []:
        text = _esc(c.get("text"))
        if c.get("href"):
            inner = f'<a href="{html_mod.escape(str(c["href"]), quote=True)}">{text}</a>'
        elif c.get("cls"):
            inner = f'<span class="{html_mod.escape(str(c["cls"]), quote=True)}">{text}</span>'
        else:
            inner = text
        parts.append(inner)
    return '<span class="sep">|</span>'.join(parts)


SKELETON_CSS = """
  @page { size: A4; margin: 13mm 14mm; }
  :root { --ink: #16181d; --body: #2f333b; --muted: #6b7280; --rule: #d8dce2; --accent: #1a1d23; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 10.2pt; line-height: 1.45; color: var(--body); -webkit-font-smoothing: antialiased; }
  .page { max-width: 190mm; margin: 0 auto; padding: 3mm 0; }
  h1 { font-family: Georgia, "Times New Roman", serif; font-size: 25pt; letter-spacing: .012em;
    color: var(--ink); margin: 0 0 3px; font-weight: 600; }
  .tagline { font-size: 10.6pt; color: var(--accent); font-weight: 600; letter-spacing: .015em; margin-bottom: 6px; }
  .contact { font-size: 8.9pt; color: var(--muted); border-top: 1px solid var(--rule); padding-top: 6px; white-space: nowrap; }
  .contact a { color: var(--muted); text-decoration: none; }
  .contact .sep { margin: 0 5px; color: #c3c8d0; }
  .avail { color: #1a1d23; font-weight: 600; }
  h2 { font-family: Georgia, "Times New Roman", serif; font-size: 11pt; font-weight: 600; color: var(--ink);
    text-transform: uppercase; letter-spacing: .1em; margin: 13px 0 7px; padding-bottom: 4px; border-bottom: 1.2px solid var(--ink); }
  .summary { margin-bottom: 2px; }
  .summary p { margin: 0 0 6px; }
  .role { margin-bottom: 10px; }
  .role-head, .role-note { page-break-after: avoid; }
  li { page-break-inside: avoid; }
  .role-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 1px; }
  .role-title { font-size: 10.6pt; color: var(--ink); font-weight: 700; }
  .role-title .co { font-weight: 700; }
  .role-title .pos { font-weight: 500; }
  .role-when { font-size: 9pt; color: var(--muted); white-space: nowrap; font-variant-numeric: tabular-nums; }
  .role-note { font-size: 9pt; color: var(--muted); font-style: italic; margin-bottom: 4px; }
  ul { margin: 4px 0 0; padding-left: 15px; }
  li { margin-bottom: 3.5px; }
  li::marker { color: #9aa1ac; }
  strong { color: var(--ink); font-weight: 650; }
  .skills { display: grid; grid-template-columns: 1fr; gap: 3px; }
  .skills div { padding-left: 0; }
  .skills b { color: var(--ink); font-weight: 650; }
  .edu { margin-bottom: 7px; }
  .edu-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
  .edu-deg { color: var(--ink); font-weight: 650; font-size: 10.3pt; }
  .edu-sub { font-size: 9.4pt; color: var(--muted); }
  .pubs { font-size: 9.5pt; }
  .pubs li { margin-bottom: 3px; }
  .pubs em { color: var(--body); }
  .service { font-size: 9.3pt; color: var(--muted); margin-top: 3px; }
  a { color: inherit; }
"""


def _render_html(content: dict[str, Any], profile: dict[str, Any]) -> str:
    """结构化内容 + 固定身份 → 完整 HTML。样式/骨架代码保证一致，定制官管不到这层。"""
    name = _esc(profile.get("name"))
    tagline = _esc(content.get("tagline"))
    contact_html = _contact_html(profile.get("contact") or [])
    summary_html = "".join(f"<p>{_rich(p)}</p>"
                           for p in (content.get("summary") or []) if str(p).strip())

    roles = []
    for r in content.get("experience") or []:
        note = (f'<div class="role-note">{_rich(r.get("note"))}</div>'
                if str(r.get("note") or "").strip() else "")
        bullets = "".join(f"<li>{_rich(b)}</li>" for b in r.get("bullets") or [] if str(b).strip())
        roles.append(
            f'<div class="role"><div class="role-head">'
            f'<div class="role-title"><span class="co">{_esc(r.get("company"))}</span> '
            f'<span class="pos">— {_esc(r.get("position"))}</span></div>'
            f'<div class="role-when">{_esc(r.get("when"))}</div></div>'
            f'{note}<ul>{bullets}</ul></div>')

    skills_html = "".join(
        f'<div><b>{_esc(s.get("label"))}</b> — {_esc(s.get("value"))}</div>'
        for s in content.get("skills") or [] if str(s.get("value") or "").strip())

    edus = []
    for e in content.get("education") or []:
        sub = (f'<div class="edu-sub">{_rich(e.get("sub"))}</div>'
               if str(e.get("sub") or "").strip() else "")
        edus.append(
            f'<div class="edu"><div class="edu-head">'
            f'<div class="edu-deg">{_esc(e.get("degree"))} — {_esc(e.get("institution"))}</div>'
            f'<div class="role-when">{_esc(e.get("when"))}</div></div>{sub}</div>')

    # 段落有内容才出小标题——此前 Summary/Experience/Skills/Education 四个标题
    # 无条件渲染，education 为空时简历（与 PDF）上就留一个光秃秃的「Education」，
    # v2 里它还夹在 Skills 与 Publications 中间。
    summary_section = f"<h2>Summary</h2>\n  <div class=\"summary\">{summary_html}</div>" \
        if summary_html else ""
    experience_section = f"<h2>Experience</h2>\n  {''.join(roles)}" if roles else ""
    skills_section = f"<h2>Technical Skills</h2>\n  <div class=\"skills\">{skills_html}</div>" \
        if skills_html else ""
    education_section = f"<h2>Education</h2>\n  {''.join(edus)}" if edus else ""

    pubs = [p for p in content.get("publications") or [] if str(p).strip()]
    pubs_section = ""
    if pubs:
        pubs_li = "".join(f"<li>{_rich(p)}</li>" for p in pubs)
        service = str(content.get("service") or "").strip()
        service_html = f'<div class="service">{_esc(service)}</div>' if service else ""
        pubs_section = (f'<h2>Selected Publications &amp; Service</h2>'
                        f'<ul class="pubs">{pubs_li}</ul>{service_html}')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{name} — {tagline}</title>
<style>{SKELETON_CSS}</style>
</head>
<body>
<div class="page">
  <header>
    <h1>{name}</h1>
    <div class="tagline">{tagline}</div>
    <div class="contact">{contact_html}</div>
  </header>
  {summary_section}
  {experience_section}
  {skills_section}
  {education_section}
  {pubs_section}
</div>
</body>
</html>
"""


def _company_intel(cfg, company: str) -> str:
    """尽调摘要 + 时间线「通话」类条目摘录——判断定位角度用，不是事实来源。
    复用 prep.py 已有的摘要逻辑，预算压到远小于 brief 生成用的量，不重新引入母版
    那种体量的输入膨胀。没有尽调/没有通话记录时返回空串，整段 prompt 里就不出现。"""
    from joblander.prep import _dossier, _timeline_digest

    summary = str((_dossier(cfg, company) or {}).get("summary_md") or "").strip()[:3000]
    digest = _timeline_digest(cfg, company, cap=3000)
    if digest.strip() == "（时间线为空）":
        digest = ""
    if not summary and not digest:
        return ""
    parts = ["【该公司情报——尽调摘要 + 时间线通话/笔记摘录，只用来判断定位角度和取舍，"
             "不是简历事实来源，弹药库之外的信息不得写进简历】"]
    if summary:
        parts.append(f"尽调摘要：\n{summary}")
    if digest:
        parts.append(f"时间线摘录（旧→新，近的事优先保全）：\n{digest}")
    return "\n\n".join(parts) + "\n\n"


def customise(cfg, llm, company: str, *, jd: str = "", feedback: str = "",
              notion_client=None) -> dict[str, Any]:
    """生成一版定制简历——单轮：弹药库 + JD + 累积修改意见集合 → 结构化内容 → 渲染。
    不基于母版、不基于上一版 HTML：每次都从当前完整意见集合整份重新生成。
    返回 {version, html, pdf, sentinel}。"""
    from joblander.company import mine_jd, save_meta
    from joblander.eventlog import EventLog
    from joblander.scribe import _strip_fences
    from joblander.sentinel import Sentinel

    bank_p = cfg.workspace_dir / "03-materials" / "achievement-bank.md"
    bank = bank_p.read_text(encoding="utf-8") if bank_p.exists() else ""
    if not bank.strip():
        raise ValueError("弹药库为空——先去弹药库写战绩")
    profile = _load_profile(cfg)

    state = resume_state(cfg, company)
    fb = list(state.get("feedback") or [])
    feedback = (feedback or "").strip()
    if feedback and feedback not in fb:
        fb.append(feedback)
    if not jd:
        row = {"Company": company}
        try:
            from joblander.prep import _load_projection, find_row
            row = find_row(_load_projection(cfg), company) or row
        except Exception:
            pass
        jd, _origin = mine_jd(cfg, row, notion_client=notion_client)

    fb_block = ("【修改意见集合（累积，逐条精确执行；没冲突就都要落实，冲突以最新一条为准）】\n"
                + "\n".join(f"- {x}" for x in fb) + "\n\n") if fb else ""
    intel_block = _company_intel(cfg, company)
    prompt = (f"【目标公司】{company}\n\n"
              f"【JD】\n{(jd or '（无 JD——按公司名与弹药库做通用向定制，并保守取舍）')[:12000]}\n\n"
              f"{intel_block}"
              f"【弹药库（唯一事实来源，含使用注意）】\n{bank[:60000]}\n\n"   # 文末是红线段，截断=丢纪律
              f"{fb_block}"
              "按系统提示的 JSON schema 输出这版定制内容。")
    try:
        raw = json.loads(_strip_fences(llm.generate(prompt, system=RESUME_SYSTEM, json_mode=True)))
    except (json.JSONDecodeError, ValueError):
        raise ValueError("Agent 产出不是合法定制内容——重试一次") from None
    if not isinstance(raw, dict) or not raw.get("experience"):
        raise ValueError("Agent 产出不是合法定制内容——重试一次")
    changes = [str(x).strip() for x in (raw.get("changes") or []) if str(x).strip()][:8]

    out_html = _render_html(raw, profile)
    verdict = Sentinel.from_config(cfg).check(out_html)
    if verdict.action.value == "block":
        raise ValueError(f"红线拦截，拒绝落盘：{verdict.explain()}")

    n = len(state.get("versions") or []) + 1
    d = resume_dir(cfg, company)
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"resume-v{n}.html"
    out.write_text(out_html, encoding="utf-8")
    pdf = _to_pdf(out)

    ver = {"v": n, "file": f"resume-v{n}", "at": datetime.now(SGT).strftime("%Y-%m-%d %H:%M"),
           "note": (feedback if feedback else
                    ("首版：弹药库 × JD 自动定制" if n == 1 else "基于累积意见重新生成"))[:120],
           "changes": changes, "pdf": bool(pdf), "sentinel": verdict.action.value}
    state.setdefault("versions", []).append(ver)
    state["current"] = ver["file"]
    state["feedback"] = fb
    save_meta(cfg, company, {"resume": state})
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "resume.customised", "agent:resume_customiser",
        {"company": company, "v": n, "feedback": bool(fb), "pdf": bool(pdf), "jd_chars": len(jd or "")})
    return {"version": ver, "html": str(out),
            "pdf": str(pdf) if pdf else "", "sentinel": verdict.action.value}


def reset(cfg, company: str) -> dict[str, Any]:
    """清空重来：版本文件 + 对话史整体归档到 resume/archive-<ts>/（不物理删除），
    meta.resume 归零（versions/feedback/asked_user 全清——教练记忆从头开始）。
    「投出的版本」记录（meta.resume_variant）是投递事实，保留不动。"""
    from joblander.company import save_meta
    from joblander.eventlog import EventLog

    d = resume_dir(cfg, company)
    moved = 0
    if d.exists():
        arch = d / f"archive-{datetime.now(SGT).strftime('%Y%m%d-%H%M%S')}"
        for p in sorted(d.iterdir()):
            if p.is_file():
                arch.mkdir(parents=True, exist_ok=True)
                p.rename(arch / p.name)
                moved += 1
    save_meta(cfg, company, {"resume": {"current": "", "versions": [], "feedback": []}})
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "resume.reset", "agent:resume_customiser", {"company": company, "archived": moved})
    return {"archived": moved}
