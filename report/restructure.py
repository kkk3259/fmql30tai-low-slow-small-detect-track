# -*- coding: utf-8 -*-
"""restructure.py —— 章节结构重整 + 格式统一（对齐参考报告）。

参考报告的章节骨架：
  第一部分  作品概述
    1.1 功能与特性 / 1.2 应用领域 / 1.3 主要技术特点
    1.4 主要性能指标 / 1.5 主要创新点 / 1.6 赛题完成情况
  第二部分  系统组成及功能说明
    2.1 整体介绍 / 2.2 硬件系统介绍 / 2.3 软件系统介绍
      2.3.1 / 2.3.2 …（三级）
  第三部分  完成情况及性能参数
    3.1 整体介绍 / 3.2 工程成果（3.2.1 电路成果…）/ 3.3 特性成果（3.3.1…）
  第四部分  总结
    4.1 作品总结 / 4.2 可扩展之处
  第五部分  参考文献
  第六部分  附录

我们报告的模板锚点带括号说明且无编号，本脚本做两件事：
  ① 按映射表把锚点标题改写成「编号 + 简述」，并挂到 Heading 1/2/3
  ② 强制段落级直接格式（字号/字体/缩进），不依赖样式继承
"""
import sys
import re

from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.style import WD_STYLE_TYPE

SRC = r"D:\lowslow\out_report_toc.docx"
DST = r"D:\lowslow\out_report_restruct.docx"

# 模板锚点（原文） → 正式标题。顺序无关，靠精确/前缀匹配。
# level: 1=Heading1  2=Heading2  3=Heading3
TITLE_MAP = [
    # ── 第一部分 ──
    ("功能与特性", "1.1 功能与特性", 2),
    ("应用领域", "1.2 应用领域", 2),
    ("主要技术特点", "1.3 主要技术特点", 2),
    ("主要性能指标", "1.4 主要性能指标", 2),
    ("主要创新点", "1.5 主要创新点", 2),
    ("设计流程", "1.6 设计流程", 2),
    # ── 第二部分 ──
    ("整体介绍（整个系统实物的正面", "3.1 整体介绍", 2),   # 先匹配长的，防误吞
    ("整体介绍", "2.1 整体介绍", 2),
    ("硬件系统介绍", "2.2 硬件系统介绍", 2),
    ("软件系统介绍", "2.3 软件系统介绍", 2),
    ("2.3.1 软件整体介绍", "2.3.1 软件整体介绍", 3),
    ("2.3.2 软件各模块介绍", "2.3.2 软件各模块介绍", 3),
    # ── 第三部分 ──
    ("工程成果（分硬件实物", "3.2 工程成果", 2),
    ("特性成果（逐个展示功能", "3.3 特性成果", 2),
    # ── 第四部分 ──
    ("可扩展之处", "4.1 可扩展之处", 2),
    ("心得体会", "4.2 心得体会", 2),
]

# 三级标题（正文里已有的 2.2.x / 3.2.x）
PAT_L3 = re.compile(r"^\d+\.\d+\.\d+\s*\S")

KEEP_OUT = ("（如果有的话", "（从总体到局部", "（图文结合", "阐述具体", "阐述最终")


def set_direct_font(para, ascii_font, ea_font, size, bold=None):
    """段落级直接格式（覆盖样式，避免样式改造不生效的问题）。"""
    for r in para.runs:
        r.font.size = Pt(size)
        r.font.name = ascii_font
        if bold is not None:
            r.font.bold = bold
        rpr = r._element.find(qn("w:rPr"))
        if rpr is None:
            rpr = OxmlElement("w:rPr")
            r._element.insert(0, rpr)
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.insert(0, rf)
        rf.set(qn("w:ascii"), ascii_font)
        rf.set(qn("w:hAnsi"), ascii_font)
        rf.set(qn("w:eastAsia"), ea_font)


def set_para_format(para, center=False, line_spacing=None,
                    before=None, after=None, first_indent=None):
    pf = para.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.LEFT
    pf.left_indent = Pt(0)
    pf.first_line_indent = Pt(first_indent) if first_indent is not None else Pt(0)
    if line_spacing is not None:
        pf.line_spacing = line_spacing
    pf.space_before = Pt(before if before is not None else 0)
    pf.space_after = Pt(after if after is not None else 0)


def set_outline(para, level):
    """段落级大纲级别 —— TOC \\o 靠它收录。

    样式级设 outlineLvl 时若 pPr 被 append 到 rPr 之后会违反 schema 顺序而失效，
    因此这里改为在段落 pPr 上直接设置（pPr 内 outlineLvl 位于 pStyle 之后，合法）。
    """
    ppr = para._element.find(qn("w:pPr"))
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        para._element.insert(0, ppr)
    ol = ppr.find(qn("w:outlineLvl"))
    if ol is None:
        ol = OxmlElement("w:outlineLvl")
        ppr.append(ol)
    ol.set(qn("w:val"), str(level))


def ensure_style(doc, name, style_id, ascii_font, ea_font, size, bold,
                 center=False, line_spacing=None, before=0, after=0, outline=None):
    """按 styleId 复用已有样式（中文 Word 的 Heading 3 叫「标题 31」）。"""
    st = None
    for s in doc.styles:
        if s.type == WD_STYLE_TYPE.PARAGRAPH and s.style_id == style_id:
            st = s
            break
    if st is None:
        try:
            st = doc.styles[name]
        except KeyError:
            st = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
            st.base_style = doc.styles["Normal"]
    st.font.size = Pt(size)
    st.font.bold = bold
    st.font.name = ascii_font
    rpr = st.element.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        st.element.append(rpr)
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.insert(0, rf)
    rf.set(qn("w:ascii"), ascii_font)
    rf.set(qn("w:hAnsi"), ascii_font)
    rf.set(qn("w:eastAsia"), ea_font)
    pf = st.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.LEFT
    pf.left_indent = Pt(0)
    pf.first_line_indent = Pt(0)
    if line_spacing is not None:
        pf.line_spacing = line_spacing
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    if outline is not None:
        ppr = st.element.find(qn("w:pPr"))
        if ppr is None:
            ppr = OxmlElement("w:pPr")
            st.element.append(ppr)
        ol = ppr.find(qn("w:outlineLvl"))
        if ol is None:
            ol = OxmlElement("w:outlineLvl")
            ppr.append(ol)
        ol.set(qn("w:val"), str(outline))
    return st


def main(src=SRC, dst=DST):
    doc = Document(src)

    # ── ① 三个标题样式（按 styleId 复用，中文名也认）──
    h1 = ensure_style(doc, "Heading 1", "1", "Times New Roman", "宋体", 16, True,
                      center=True, before=12, after=12, outline=0)
    h2 = ensure_style(doc, "Heading 2", "2", "Times New Roman", "楷体", 14, True,
                      center=False, line_spacing=1.0, before=10, after=10, outline=1)
    h3 = ensure_style(doc, "Heading 3", "31", "Times New Roman", "楷体", 12, True,
                      center=False, line_spacing=1.73, before=13, after=13, outline=2)
    print("  OK  标题样式：H1(16pt居中) / H2(14pt楷体) / H3(12pt楷体，复用 styleId=31)")

    # ── ② 正文：12pt 宋体 单倍 首行 21pt ──
    for nm in ("Normal", "List Paragraph"):
        st = doc.styles[nm]
        st.font.size = Pt(12)
        st.font.name = "Times New Roman"
        rpr = st.element.find(qn("w:rPr"))
        if rpr is None:
            rpr = OxmlElement("w:rPr")
            st.element.append(rpr)
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.insert(0, rf)
        rf.set(qn("w:ascii"), "Times New Roman")
        rf.set(qn("w:hAnsi"), "Times New Roman")
        rf.set(qn("w:eastAsia"), "宋体")
        pf = st.paragraph_format
        pf.line_spacing = 1.0
        pf.first_line_indent = Pt(21)
        pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        pf.left_indent = Pt(0)
    print("  OK  正文：12pt 宋体 单倍 首行21pt 两端对齐")

    # ── ③ 标题改写（映射表）──
    n_map = 0
    SKIP_TAIL = ("；", ";", "）", ")")
    for p in doc.paragraphs:
        t = p.text.strip()
        if not t or len(t) > 60:
            continue
        sid = (p.style.style_id or "").upper()
        if sid.startswith("TOC"):
            continue
        if "\t" in t:                      # 目录条目（带 tab 页码）
            continue
        if any(k in t for k in KEEP_OUT):
            continue

        # ① 先查映射表：模板锚点即使带括号说明（如「整体介绍（整个系统实物的…）」）
        #    也要改写成带编号的正式标题 —— 它们在映射表里，是「真标题」
        hit = False
        for anchor, title, level in TITLE_MAP:
            if t.startswith(anchor) and t != title:
                for r in list(p.runs):
                    r._element.getparent().remove(r._element)
                # H1/H2 由 Word 多级列表自动编号，文字里不再重复写数字；
                # H3 用的「标题 31」未绑定编号，保留文字编号
                disp = re.sub(r"^\d+(\.\d+)*\s+", "", title) if level <= 2 else title
                p.add_run(disp)
                p.style = {1: h1, 2: h2, 3: h3}[level]
                n_map += 1
                hit = True
                break
        if hit:
            continue

        # ② 不在映射表里：以分号/括号结尾的是模板占位提示，跳过
        if t.endswith(SKIP_TAIL):
            continue
        # ③ 已是正式编号的三级标题（2.2.2 / 3.2.x）
        if PAT_L3.match(t) and len(t) <= 32:
            p.style = h3
            n_map += 1
    print("  OK  标题改写：%d 个（映射 + 三级）" % n_map)

    # ── ④ 第一部分~第五部分 → Heading 1 ──
    n_part = 0
    for p in doc.paragraphs:
        t = p.text.strip()
        if "\t" in t:                      # 目录条目不算章标题
            continue
        if re.match(r"^第[一二三四五六七八九十]部分", t) and len(t) <= 30:
            p.style = h1
            n_part += 1
    print("  OK  章标题 → H1：%d 个" % n_part)

    # ── ⑤ 段落级直接格式兜底（防止样式继承失效）──
    FMT = {
        "Heading 1": dict(size=16, ea="宋体", bold=True, center=True, ls=None, b=12, a=12),
        "Heading 2": dict(size=14, ea="楷体", bold=True, center=False, ls=1.0, b=10, a=10),
        "Heading 3": dict(size=12, ea="楷体", bold=True, center=False, ls=1.73, b=13, a=13),
        "标题 31":   dict(size=12, ea="楷体", bold=True, center=False, ls=1.73, b=13, a=13),
    }
    n_direct = 0
    for p in doc.paragraphs:
        nm = p.style.name
        cfg = FMT.get(nm)
        if not cfg or not p.text.strip():
            continue
        set_direct_font(p, "Times New Roman", cfg["ea"], cfg["size"], cfg["bold"])
        set_para_format(p, center=cfg["center"], line_spacing=cfg["ls"],
                        before=cfg["b"], after=cfg["a"], first_indent=0)
        # 段落级大纲级别（TOC \o 依赖它，样式级设置不生效）
        lvl = {"Heading 1": 0, "Heading 2": 1, "Heading 3": 2, "标题 31": 2}.get(nm)
        if lvl is not None:
            set_outline(p, lvl)
        n_direct += 1
    print("  OK  标题段落直接格式：%d 个" % n_direct)

    # ── ⑥ 作品名称/目录/图目录/表目录：挂到不进 TOC 的样式 ──
    try:
        toc_h = doc.styles["TOCHeading"]
    except KeyError:
        toc_h = doc.styles.add_style("TOCHeading", WD_STYLE_TYPE.PARAGRAPH)
        toc_h.base_style = doc.styles["Normal"]
    toc_h.font.size = Pt(16)
    toc_h.font.bold = True
    toc_h.font.name = "Times New Roman"
    _rpr = toc_h.element.find(qn("w:rPr"))
    if _rpr is None:
        _rpr = OxmlElement("w:rPr")
        toc_h.element.append(_rpr)
    _rf = _rpr.find(qn("w:rFonts"))
    if _rf is None:
        _rf = OxmlElement("w:rFonts")
        _rpr.insert(0, _rf)
    _rf.set(qn("w:ascii"), "Times New Roman")
    _rf.set(qn("w:hAnsi"), "Times New Roman")
    _rf.set(qn("w:eastAsia"), "宋体")
    _pf = toc_h.paragraph_format
    _pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _pf.first_line_indent = Pt(0)
    _pf.left_indent = Pt(0)
    _pf.space_before = Pt(12)
    _pf.space_after = Pt(12)
    _ppr = toc_h.element.find(qn("w:pPr"))
    if _ppr is None:
        _ppr = OxmlElement("w:pPr")
        toc_h.element.append(_ppr)
    _ol = _ppr.find(qn("w:outlineLvl"))
    if _ol is None:
        _ol = OxmlElement("w:outlineLvl")
        _ppr.append(_ol)
    _ol.set(qn("w:val"), "9")        # 正文级别，不进 TOC

    FRONT = ("作品名称", "目录", "图目录", "表目录")
    n_front = 0
    for _p in doc.paragraphs:
        if _p.text.strip() in FRONT:
            _p.style = toc_h
            set_direct_font(_p, "Times New Roman", "宋体", 16, True)
            set_para_format(_p, center=True, before=12, after=12, first_indent=0)
            set_outline(_p, 9)      # 段落级设为正文级别，TOC \o 不会收录
            n_front += 1
    print("  OK  作品名称/目录/图目录/表目录：%d 个改为不进 TOC" % n_front)

    # ── ⑦ 表格：边框 + 表头 12pt 粗体居中 ──
    for tbl in doc.tables:
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
            e.set(qn("w:val"), "single"); e.set(qn("w:sz"), "4")
            e.set(qn("w:space"), "0"); e.set(qn("w:color"), "000000")
            b.append(e)
        tblPr.append(b)
        for ri, row in enumerate(tbl.rows):
            for cell in row.cells:
                for para in cell.paragraphs:
                    para.paragraph_format.first_line_indent = Pt(0)
                    para.paragraph_format.left_indent = Pt(0)
                    if ri == 0:
                        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    for r in para.runs:
                        r.font.size = Pt(12)
                        if ri == 0:
                            r.font.bold = True
    print("  OK  表格：%d 个（边框 + 表头 12pt 粗体居中）" % len(doc.tables))

    # ── ⑧ 改写三个 TOC 域 ──
    # 目录必须用 \o "1-3"（按 Heading 的大纲级别收录）；此前 add_toc.py 写的是
    # \t "ChapterTitle,1"，而 ChapterTitle 样式在本脚本里已无段落，会导致目录为空。
    NEW_INSTR = {
        "目录":   'TOC \\o "1-3" \\h \\z \\u',
        "图目录": 'TOC \\h \\z \\t "FigCaption,1"',
        "表目录": 'TOC \\h \\z \\t "TableCaption,1"',
    }
    _paras = doc.paragraphs
    _marks = {}
    for _i, _p in enumerate(_paras):
        _t = _p.text.strip()
        if _t in NEW_INSTR and _t not in _marks:
            _marks[_t] = _i
    n_toc = 0
    for _name, _idx in _marks.items():
        for _j in range(_idx + 1, min(_idx + 6, len(_paras))):
            _ins = _paras[_j]._element.findall(".//" + qn("w:instrText"))
            if _ins:
                _ins[0].text = " %s " % NEW_INSTR[_name]
                n_toc += 1
                break
    print("  OK  TOC 域：%d 个已改写" % n_toc)

    doc.save(dst)
    print("\n  已生成：%s" % dst)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else SRC, a[1] if len(a) > 1 else DST)
