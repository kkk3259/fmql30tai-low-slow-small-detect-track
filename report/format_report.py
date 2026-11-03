# -*- coding: utf-8 -*-
"""format_report.py —— 把报告格式对齐参考报告（01 基于FPGA的智能信号采集与分析系统）。

参考报告的实测规格（取自段落直接格式，而非样式默认值）：
  Heading 1  Times New Roman        16pt  居中     ← 「第一部分 …」「摘要」
  Heading 2  Times New Roman + 楷体  14pt  左对齐   ← 「1.1 功能与特性」
  Heading 3  Times New Roman + 楷体  12pt  行距1.73 段前段后13pt ← 「2.3.1 …」
  正文       Times New Roman + 宋体  12pt  首行缩进 21pt（2字符）单倍行距 两端对齐
  表格       Table Grid（有边框）    首格 12pt 粗体 居中
  题注       Arial + 黑体            10pt  居中

做法：只改样式与段落级别，不动任何文字内容。
"""
import sys
import re

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

SRC = r"D:\lowslow\out_report_toc.docx"
DST = r"D:\lowslow\out_report_fmt.docx"

# 标题判定：短（<40 字）、无句号、以「第X部分」或数字编号开头
PAT_PART = re.compile(r"^第[一二三四五六七八九十]部分")
PAT_L2 = re.compile(r"^\d+\.\d+\s*\S")          # 1.1 / 2.3
PAT_L3 = re.compile(r"^\d+\.\d+\.\d+\s*\S")     # 2.3.1
KEEP_OUT = ("（如果有的话", "（从总体到局部", "（图文结合", "阐述具体", "阐述最终",
            "（实物照片）", "（界面照片）", "（实物）", "（界面）")
SKIP_TAIL = ("；", ";")   # 以分号结尾的是模板占位提示，不是真标题


def set_font(style_or_run, ascii_font, ea_font, size, bold=None):
    """统一设置中西文字体与字号。"""
    f = style_or_run.font
    f.name = ascii_font
    f.size = Pt(size)
    if bold is not None:
        f.bold = bold
    el = style_or_run.element
    rpr = el.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        # rPr 必须是 pPr/rPr 或 r/rPr，样式级直接插到 style 元素
        el.append(rpr)
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.insert(0, rf)
    rf.set(qn("w:ascii"), ascii_font)
    rf.set(qn("w:hAnsi"), ascii_font)
    rf.set(qn("w:eastAsia"), ea_font)


def ensure_heading_style(doc, name, ascii_font, ea_font, size, bold,
                         center=False, line_spacing=None,
                         before=None, after=None,
                         style_ids=()):
    """建立/改造成参考报告那样的标题样式。

    中文版 Word 的内置标题样式名可能是「标题 3」而非「Heading 3」，
    因此除了按名字找，还允许按 styleId（如 "3" / "31"）兜底。
    """
    st = None
    try:
        st = doc.styles[name]
    except KeyError:
        for _s in doc.styles:
            if _s.type == WD_STYLE_TYPE.PARAGRAPH and _s.style_id in style_ids:
                st = _s
                break
        if st is None:
            st = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    st.base_style = doc.styles["Normal"]
    set_font(st, ascii_font, ea_font, size, bold)
    pf = st.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.LEFT
    pf.first_line_indent = Pt(0)
    pf.left_indent = Pt(0)
    if line_spacing is not None:
        pf.line_spacing = line_spacing
    if before is not None:
        pf.space_before = Pt(before)
    if after is not None:
        pf.space_after = Pt(after)
    # 大纲级别（导航窗格靠它）
    lvl = {"Heading 1": 0, "Heading 2": 1, "Heading 3": 2}.get(name)
    if lvl is None:
        lvl = {"1": 0, "2": 1, "3": 2, "31": 2}.get(st.style_id)
    if lvl is not None:
        ppr = st.element.find(qn("w:pPr"))
        if ppr is None:
            ppr = OxmlElement("w:pPr")
            st.element.append(ppr)
        ol = ppr.find(qn("w:outlineLvl"))
        if ol is None:
            ol = OxmlElement("w:outlineLvl")
            ppr.append(ol)
        ol.set(qn("w:val"), str(lvl))
    return st


def main(src=SRC, dst=DST):
    doc = Document(src)
    styles = doc.styles

    # ── ① 正文：12pt / 宋体 / 单倍行距 / 首行缩进 21pt / 两端对齐 ──
    for name in ("Normal", "List Paragraph"):
        st = styles[name]
        set_font(st, "Times New Roman", "宋体", 12)
        pf = st.paragraph_format
        pf.line_spacing = 1.0
        pf.first_line_indent = Pt(21)
        pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
    print("  OK  正文样式（Normal / List Paragraph）→ 12pt 宋体 单倍 首行21pt")

    # ── ② 三级标题样式 ──
    h1 = ensure_heading_style(doc, "Heading 1", "Times New Roman", "宋体",
                              16, True, center=True, before=12, after=12)
    h2 = ensure_heading_style(doc, "Heading 2", "Times New Roman", "楷体",
                              14, True, center=False, line_spacing=1.0,
                              before=10, after=10)
    h3 = ensure_heading_style(doc, "Heading 3", "Times New Roman", "楷体",
                              12, True, center=False, line_spacing=1.73,
                              before=13, after=13,
                              style_ids=("3", "31"))
    print("  OK  标题样式：H1 16pt居中 / H2 14pt楷体 / H3 12pt楷体")

    # ── ③ 题注样式对齐参考（Arial + 黑体 10pt 居中）──
    for nm in ("FigCaption", "TableCaption"):
        try:
            st = styles[nm]
            set_font(st, "Arial", "黑体", 10)
            st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
            st.paragraph_format.first_line_indent = Pt(0)
        except KeyError:
            pass
    print("  OK  题注样式：Arial + 黑体 10pt 居中")

    # ── ④ 重新分级标题 ──
    n_h1 = n_h2 = n_h3 = 0
    skip = 0
    for p in doc.paragraphs:
        t = p.text.strip()
        if not t or len(t) > 40 or t.endswith("。"):
            continue
        # 目录条目（toc 1 / toc 2 / TOC1 / TOC2 样式）不能当标题改层级，
        # 否则会把已生成的目录内容污染成三级标题
        sid = (p.style.style_id or "").upper()
        if sid.startswith("TOC") or "目录" in p.style.name.lower():
            skip += 1
            continue
        if any(k in t for k in KEEP_OUT) or t.endswith(SKIP_TAIL):
            skip += 1
            continue
        if PAT_PART.match(t):
            p.style = h1
            n_h1 += 1
        elif PAT_L3.match(t):
            p.style = h3
            n_h3 += 1
        elif PAT_L2.match(t):
            p.style = h2
            n_h2 += 1

    # 上一版 add_toc.py 把章标题与无编号小节都挂到了 ChapterTitle，
    # 这里按内容重新分流：第X部分 → H1，其余（功能与特性/应用领域…）→ H2
    n_from_ch = 0
    for p in doc.paragraphs:
        if p.style.name != "ChapterTitle":
            continue
        t = p.text.strip()
        if not t:
            continue
        if PAT_PART.match(t):
            p.style = h1
        else:
            p.style = h2
            n_from_ch += 1
    n_h2 += n_from_ch
    print("  OK  ChapterTitle 重分流：无编号小结 %d 个 → H2" % n_from_ch)
    print("  OK  标题分级：第一部分×%d → H1 ｜ 1.x×%d → H2 ｜ x.y.z×%d → H3（跳过模板提示 %d 条）"
          % (n_h1, n_h2, n_h3, skip))

    # ── ⑤ 表格：Table Grid 边框 + 首格 12pt 粗体居中 ──
    def add_borders(tbl):
        tblPr = tbl._element.find(qn("w:tblPr"))
        if tblPr is None:
            tblPr = OxmlElement("w:tblPr")
            tbl._element.insert(0, tblPr)
        old = tblPr.find(qn("w:tblBorders"))
        if old is not None:
            tblPr.remove(old)
        b = OxmlElement("w:tblBorders")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            e = OxmlElement("w:" + side)
            e.set(qn("w:val"), "single")
            e.set(qn("w:sz"), "4")
            e.set(qn("w:space"), "0")
            e.set(qn("w:color"), "000000")
            b.append(e)
        tblPr.append(b)

    n_tbl = 0
    for tbl in doc.tables:
        add_borders(tbl)
        # 首行（表头）居中 + 粗体 + 12pt
        for cell in tbl.rows[0].cells:
            for para in cell.paragraphs:
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                para.paragraph_format.first_line_indent = Pt(0)
                for r in para.runs:
                    r.font.size = Pt(12)
                    r.font.bold = True
        # 其余单元格：12pt、取消首行缩进
        for row in tbl.rows[1:]:
            for cell in row.cells:
                for para in cell.paragraphs:
                    para.paragraph_format.first_line_indent = Pt(0)
                    for r in para.runs:
                        r.font.size = Pt(12)
        n_tbl += 1
    print("  OK  表格：%d 个加了 Table Grid 边框，表头 12pt 粗体居中" % n_tbl)

    # ── ⑥ 目录/图目录/表目录/作品名称：挂到不进 TOC 的样式 ──
    # 参考报告的导航窗格与目录都从「第一部分 作品概述」开始，前面这几个标题
    # 不是 Heading（不参与 TOC）。这里用外观相同的 TOCHeading（outlineLvl=9）实现。
    try:
        toc_h = styles["TOCHeading"]
    except KeyError:
        toc_h = styles.add_style("TOCHeading", WD_STYLE_TYPE.PARAGRAPH)
    toc_h.base_style = styles["Normal"]
    set_font(toc_h, "Times New Roman", "宋体", 16, True)
    pf = toc_h.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf.first_line_indent = Pt(0)
    pf.space_before = Pt(12)
    pf.space_after = Pt(12)
    _ppr = toc_h.element.find(qn("w:pPr"))
    if _ppr is None:
        _ppr = OxmlElement("w:pPr")
        toc_h.element.append(_ppr)
    _ol = _ppr.find(qn("w:outlineLvl"))
    if _ol is None:
        _ol = OxmlElement("w:outlineLvl")
        _ppr.append(_ol)
    _ol.set(qn("w:val"), "9")          # 9 = 正文级别，不进 TOC

    FRONT = ("目录", "图目录", "表目录", "作品名称")
    n_front = 0
    for _p in doc.paragraphs:
        if _p.text.strip() in FRONT and _p.style.name.startswith("Heading"):
            _p.style = toc_h
            n_front += 1
    print("  OK  目录/图目录/表目录/作品名称：%d 个改为不进 TOC 的样式" % n_front)

    # ── ⑦ 改写 TOC 域：目录用标准 \o（标题已全是 Heading），图/表目录仍按样式收录 ──
    from docx.oxml.ns import qn as _qn
    NEW_INSTR = {
        "目录":   'TOC \\o "1-3" \\h \\z \\u',
        "图目录": 'TOC \\h \\z \\t "FigCaption,1"',
        "表目录": 'TOC \\h \\z \\t "TableCaption,1"',
    }
    paras = doc.paragraphs
    marks = {}
    for i, _p in enumerate(paras):
        _t = _p.text.strip()
        if _t in NEW_INSTR and _t not in marks:
            marks[_t] = i
    for name, idx in marks.items():
        for j in range(idx + 1, min(idx + 6, len(paras))):
            ins = paras[j]._element.findall(".//" + _qn("w:instrText"))
            if ins:
                ins[0].text = " %s " % NEW_INSTR[name]
                break
    print("  OK  TOC 域：%d 个已改写（目录用 \\o，图/表目录用 \\t）" % len(marks))

    doc.save(dst)
    print("\n  已生成：%s" % dst)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else SRC, a[1] if len(a) > 1 else DST)
