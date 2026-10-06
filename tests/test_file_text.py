"""附件抽文本：简历、JD、转写附件都走 company._file_text，抽错了下游全吃乱码。"""

import zipfile

from joblander.company import _file_text, looks_garbled

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def _p(*runs: str) -> str:
    return "<w:p>" + "".join(f"<w:r><w:t xml:space=\"preserve\">{r}</w:t></w:r>" for r in runs) + "</w:p>"


def make_docx(path, body: str, header: str | None = None):
    """最小 Word 包：只放 _file_text 会读的几个部件。"""
    doc = f'<w:document xmlns:w="{W_NS}" xmlns:mc="{MC_NS}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", doc)
        if header is not None:
            z.writestr("word/header1.xml", f'<w:hdr xmlns:w="{W_NS}">{header}</w:hdr>')
    return path


def test_docx_reads_paragraphs_runs_tables_and_header(tmp_path):
    """2026-10-05 云端实测：.docx 落到 read_text(utf-8, errors=replace)，读出 1.1 万字符 zip 乱码
    （开头 PK…[Content_Types].xml），过了 200 字检查送进 LLM，报「换文字版简历」还扣费。"""
    textbox = ("<w:p><w:r><mc:AlternateContent>"
               f"<mc:Choice><w:txbxContent>{_p('侧栏技能 Python')}</w:txbxContent></mc:Choice>"
               f"<mc:Fallback><w:txbxContent>{_p('侧栏技能 Python')}</w:txbxContent></mc:Fallback>"
               "</mc:AlternateContent></w:r></w:p>")
    body = (_p("Acme Pay · Senior Engineer · 2021-2025")
            + _p("主导支付路由重构，", "P99 延迟从 800ms 降到 120ms")        # 一句话被拆成两个 run
            + "<w:p><w:r><w:t>技能</w:t><w:tab/><w:t>Kafka</w:t></w:r></w:p>"
            + f"<w:tbl><w:tr><w:tc>{_p('对账系统迁移')}</w:tc></w:tr></w:tbl>"
            + textbox)
    p = make_docx(tmp_path / "cv.docx", body, header=_p("张三 zhangsan@example.com"))
    text = _file_text(p)
    assert "PK" not in text and not looks_garbled(text)
    lines = text.splitlines()
    assert lines[0] == "张三 zhangsan@example.com"                   # 页眉里的联系方式也在
    assert "主导支付路由重构，P99 延迟从 800ms 降到 120ms" in lines        # run 拼回一行
    assert "技能\tKafka" in lines and "对账系统迁移" in lines
    assert text.count("侧栏技能 Python") == 1                           # 文本框 Choice/Fallback 只取一份


def test_broken_docx_reports_instead_of_garbage(tmp_path):
    p = tmp_path / "cv.docx"
    p.write_bytes(b"PK\x03\x04 not really a zip")
    assert _file_text(p).startswith("（Word 抽取失败")


def test_pdf_ligatures_restored_but_cjk_punctuation_kept(tmp_path, monkeypatch):
    """pypdf 原样吐出 \ufb01/\ufb04：「o\ufb04ine」进弹药库后 ATS 关键词对不上。只还原连字，
    不做 NFKC——NFKC 会把中文全角标点改成半角。"""
    class Page:
        def extract_text(self):
            return "o\ufb04ine evaluation, LLM \ufb01ne-tuning，对账（迁移）"

    class Reader:
        def __init__(self, path):
            self.pages = [Page()]

    monkeypatch.setattr("pypdf.PdfReader", Reader)
    p = tmp_path / "cv.pdf"
    p.write_bytes(b"%PDF-1.4")
    assert _file_text(p) == "offline evaluation, LLM fine-tuning，对账（迁移）"


def test_looks_garbled():
    assert looks_garbled(bytes(range(256)).decode("utf-8", errors="replace") * 3)
    assert not looks_garbled("张三\tSenior Engineer\n主导支付路由重构，P99 延迟从 800ms 降到 120ms\n" * 5)
    assert not looks_garbled("")
