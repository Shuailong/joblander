"""安全回归：本地 app 没有登录态，浏览器是主要攻击面。

2026-09-07 代码 review 发现三个真洞（均已实测复现）：
- /api/drill/run 直接执行表单里的 Python：任意网页自动提交表单即 RCE
- 提案端点收裸路径：reject 能改写 workspace 外任意 JSON，apply 顺着 jd_file 能删任意文件
- 全站零 CSRF / Host 校验：DNS rebinding 可读全部战线、薪资、简历
"""

import json

import pytest
from fastapi.testclient import TestClient

import joblander.notion as notion_mod
from joblander.applyops import apply_proposal, reject_proposal
from joblander.config import Config


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / "12-intake").mkdir(parents=True)
    (ws / "09-projections").mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text('{"rows": []}', encoding="utf-8")
    cfg = Config(raw={"workspace_dir": str(ws), "sentinel": {"rules": []}},
                 path=tmp_path / "c.yaml")
    monkeypatch.setattr("joblander.web.app.load_config", lambda: cfg)
    monkeypatch.setattr(notion_mod.NotionClient, "_request",
                        lambda self, *a, **k: {"results": [], "id": "created"})
    from joblander.web.app import TASKS, create_app
    TASKS.clear()
    return TestClient(create_app(with_daemon=False), base_url="http://127.0.0.1"), cfg, ws


# ---------- 跨站写操作 ----------

def test_cross_origin_post_is_refused(app_client):
    """任意网页自动提交表单打 /api/drill/run = 在用户机器上执行代码。必须拒。"""
    client, _, _ = app_client
    r = client.post("/api/drill/run",
                    data={"id": "three-sum", "code": "print(1)"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert "跨站" in r.json()["error"]


def test_cross_origin_referer_is_refused(app_client):
    """没有 Origin 时按 Referer 判。"""
    client, _, _ = app_client
    r = client.post("/api/company/flag",
                    data={"page_id": "x", "on": "1"},
                    headers={"Referer": "https://evil.example/page"})
    assert r.status_code == 403


def test_same_origin_post_passes(app_client):
    """本站页面发起的写操作照常放行——守卫不能把正常使用一起挡了。"""
    client, _, _ = app_client
    r = client.post("/api/company/flag", data={"page_id": "x", "on": "1"},
                    headers={"Origin": "http://127.0.0.1:8899"})
    assert r.status_code != 403


def test_headerless_post_passes_for_cli(app_client):
    """curl / CLI / 测试不带 Origin：放行（跨站表单浏览器一定带 Origin）。"""
    client, _, _ = app_client
    assert client.post("/api/company/flag",
                       data={"page_id": "x", "on": "1"}).status_code != 403


def test_foreign_host_header_is_refused(app_client):
    """DNS rebinding：恶意域名解析到 127.0.0.1，浏览器带的是它自己的 Host。
    读接口同样要挡——战线、薪资、简历都在这后面。"""
    client, _, _ = app_client
    r = client.get("/pipeline", headers={"Host": "evil.example"})
    assert r.status_code == 421
    assert client.get("/pipeline", headers={"Host": "localhost:8899"}).status_code == 200


# ---------- 提案路径夹紧 ----------

def test_reject_refuses_path_outside_workspace(app_client, tmp_path):
    """此前：把任意 JSON 改写成带 approved:false 的内容。"""
    _, cfg, _ = app_client
    outside = tmp_path / "victim.json"
    outside.write_text('{"important": true}', encoding="utf-8")

    with pytest.raises(ValueError, match="越界"):
        reject_proposal(cfg, outside)

    assert json.loads(outside.read_text()) == {"important": True}   # 没被动


def test_apply_refuses_path_outside_proposal_dirs(app_client, tmp_path):
    _, cfg, ws = app_client
    inside_ws_but_wrong = ws / "notes.json"
    inside_ws_but_wrong.write_text('{"kind": "x"}', encoding="utf-8")
    with pytest.raises(ValueError, match="越界"):
        apply_proposal(cfg, inside_ws_but_wrong, yes=True)
    with pytest.raises(ValueError, match="越界"):
        apply_proposal(cfg, tmp_path / "elsewhere.json", yes=True)


def test_apply_jd_file_cannot_escape_workspace(app_client, tmp_path):
    """提案里的 jd_file 下游是 unlink：绝对路径 / .. 都不能碰到 workspace 外的文件。"""
    _, cfg, ws = app_client
    victim = tmp_path / "precious.pdf"
    victim.write_bytes(b"do not delete")
    prop = ws / "12-intake" / "lead.json"
    prop.write_text(json.dumps({
        "kind": "lead.intake",
        "lead": {"company": "Acme", "position": "Eng"},
        "jd_file": str(victim),          # 绝对路径：workspace_dir / 它 == 它
    }, ensure_ascii=False), encoding="utf-8")

    apply_proposal(cfg, prop, yes=True)

    assert victim.exists(), "workspace 外的文件被提案删掉了"


# ---------- Notion 可选 ----------

def test_approve_works_without_notion_configured(app_client):
    """README 说 Notion 可选。此前无条件读 cfg.raw['notion'] → 纯本地用户
    一批准提案就 KeyError，提案制这个核心闸门整个不可用。"""
    _, cfg, ws = app_client
    assert "notion" not in cfg.raw
    prop = ws / "12-intake" / "lead.json"
    prop.write_text(json.dumps({
        "kind": "lead.intake",
        "lead": {"company": "Acme", "position": "Eng", "highlight": "x"},
    }, ensure_ascii=False), encoding="utf-8")

    out = apply_proposal(cfg, prop, yes=True)

    assert out["dry_run"] is False
    assert "skipped" in str(out.get("notion", ""))
    from joblander.company import local_entries
    assert local_entries(cfg, "Acme"), "本地档案该建起来"


# ---------- SSRF ----------

@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8899/system",
    "http://localhost/admin",
    "http://169.254.169.254/latest/meta-data/",     # 云元数据端点
    "http://10.0.0.5/internal",
    "http://192.168.1.1/",
    "file:///etc/passwd",
    "gopher://x/",
])
def test_fetch_url_refuses_non_public_targets(url):
    """抓取目标不完全受用户控制：Job URL 可能来自 LLM 对招聘邮件的抽取，
    尽调抓的是搜索引擎给的链接。内网/回环/元数据端点一律拒。"""
    from joblander.researcher import _check_public_url
    with pytest.raises(ValueError):
        _check_public_url(url)


def test_fetch_url_allows_public_http():
    from joblander.researcher import _check_public_url
    _check_public_url("https://example.com/jobs/1")     # 不抛即通过


# ---------- 简历里的 prompt 注入 ----------

def test_resume_render_neutralises_injected_html():
    """JD 与尽调摘要都来自抓取，注入可以让模型把标签写进简历正文；
    产物又由 /files 在浏览器里打开。白名单之外一律转义。"""
    from joblander.resume_agent import _render_html
    content = {
        "tagline": "AI Engineer",
        "summary": ['正常 <strong>数字</strong> 与 <img src=x onerror="alert(1)">'],
        "experience": [{"company": "ExCo", "position": "Eng", "when": "2020",
                        "note": "", "bullets": ["<script>steal()</script> 战绩"]}],
        "skills": [], "education": [], "publications": [], "service": "",
    }
    html = _render_html(content, {"name": "Alex Doe", "contact": []})

    assert "<strong>数字</strong>" in html            # 白名单标签保留
    # 关键是「没有真标签」，不是「没有这个词」——转义后的字面文本无害且显眼
    assert "<img" not in html and "<script" not in html
    assert 'onerror="' not in html                     # 不存在真属性
    assert "&lt;img" in html and "&lt;script&gt;" in html


def test_html_files_served_sandboxed(app_client, tmp_path):
    """附件/简历 HTML 以同源 text/html 渲染 = 同源脚本执行。CSP sandbox 剥夺脚本与同源。"""
    client, cfg, ws = app_client
    d = ws / "18-companies" / "Acme" / "attachments"
    d.mkdir(parents=True)
    (d / "evil.html").write_text("<script>fetch('/api/company/flag')</script>", encoding="utf-8")

    r = client.get("/files/18-companies/Acme/attachments/evil.html")

    assert r.status_code == 200
    assert "sandbox" in r.headers.get("content-security-policy", "")
    assert r.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.parametrize("src,expect_in,expect_not_in", [
    # 带 query 的外链：转义后 URL 含 &amp;，早期字符类整条漏掉——
    # 开标签留在转义态、闭标签却还原，产出孤立 </a> 且链接失效
    ('见 <a href="https://x.com/a?b=1&c=2">论文</a>',
     '<a href="https://x.com/a?b=1&amp;c=2">论文</a>', "&lt;a href"),
    ('<a href="javascript:alert(1)">x</a>', "&lt;a href", '<a href="javascript'),
    ('<a href="ftp://h/f">x</a>', "&lt;a href", "<a href=\"ftp"),
    ("孤立 </a> 结尾", "&lt;/a&gt;", "</a>"),          # 没开过就不许闭
    ("R&D 成本 -42%", "R&amp;D", "<"),
])
def test_rich_link_handling(src, expect_in, expect_not_in):
    from joblander.resume_agent import _rich
    out = _rich(src)
    assert expect_in in out, out
    assert expect_not_in not in out, out


def test_rich_keeps_multiple_links_balanced():
    from joblander.resume_agent import _rich
    out = _rich('<a href="https://a.com">A</a> 与 <a href="https://b.com?q=1&r=2">B</a>')
    assert out.count("<a href=") == 2 and out.count("</a>") == 2


def test_rendered_resume_is_parseable_html():
    """渲染产物必须是能解析的 HTML，且不含可执行标签。"""
    from html.parser import HTMLParser
    from joblander.resume_agent import _render_html

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags = []

        def handle_starttag(self, t, a):
            self.tags.append(t)

    content = {"tagline": "AI Eng", "summary": ["R&D 与 <strong>数字</strong>，5 < 10"],
               "experience": [{"company": "A&B Co", "position": "Eng", "when": "2020",
                               "note": "", "bullets": [
                                   '<img src=x onerror=1> 与 '
                                   '<a href="https://x.com?a=1&b=2">链接</a>']}],
               "skills": [{"label": "L", "value": "Python, C++"}],
               "education": [], "publications": [], "service": ""}
    p = P()
    p.feed(_render_html(content, {"name": "Alex & Co", "contact": [{"text": "a@b.com"}]}))
    assert "img" not in p.tags and "script" not in p.tags
    assert "a" in p.tags and "strong" in p.tags        # 合法内容没被误伤
