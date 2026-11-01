# -*- coding: utf-8 -*-
"""add_toc.py —— 给报告加「目录 / 图目录 / 表目录」三份清单（仿参考报告排版）。

为什么需要它
------------
参考报告（01 基于FPGA的智能信号采集与分析系统.docx）用的是 Word 标准图表目录机制：
图题注挂 Caption 样式、图号用 SEQ 域、目录用 TOC 域自动生成页码。我们的报告由官方
模板填充而来，章节标题是 Normal 样式（手工写「第一部分 …」）、图题注是 List Paragraph、
表根本没有题注，因此 TOC 域收不到任何东西。

本脚本不改任何版面外观，只做三件事：
  1. 新建三个「外观与现状完全一致」的样式，把对应段落挂上去
       ChapterTitle  14pt 粗体左对齐（挂「第X部分」与 1.x 小节标题）
       FigCaption    10pt 居中（挂 25 个真题注「图 X␣␣标题」）
       TableCaption  10pt 居中（挂 15 个「表 N␣␣标题」，插在表格之前）
  2. 在「关键词」段之后插入：分页 + 目录 + 分页 + 图目录 + 分页 + 表目录
  3. 三个 TOC 域分别用 \\t "样式名,1" 按样式收录

踩过的坑（勿重犯）
------------------
  · Word 自带「题注」样式，用英文名 Caption 创建会变成「题注1」，TOC 匹配不到
  · 题注与说明文字要区分：题注是「图 X + 两个空格 + 标题」，说明是「图 X + 单空格 + 谓语」
  · 表题注要用「紧邻表格的前一段」识别，不能用文本正则全表扫，
    否则目录里已生成的条目也会被误判成题注（目录自己收录自己）
  · 章节标题不要改成 Heading 1（22pt 会大幅改变版面），用同外观的自定义样式

用法
----
  python add_toc.py                 # D:\\lowslow\\out_report_img.docx -> out_report_toc.docx
  python add_toc.py in.docx out.docx
随后用 Word 更新域（见 update_fields.ps1 或在 Word 里 Ctrl+A → F9）。
"""
import sys
import re
import os

from docx import Document
from docx.shared import Pt
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph

SRC = r"D:\lowslow\out_report_img.docx"
DST = r"D:\lowslow\out_report_toc.docx"

# 15 个表格的标题（按表头与上下文推断，最终以正文表述为准）
TABLE_TITLES = [
    "主要性能指标实测（30 项）",
    "FMQL30TAI 硬件资源规格",
    "PL 电路模块与关键信号",
    "处理环节的模块划分与数据接口",
    "五个关键数据接口的形态与连接关系",
    "主要技术特点的量化结果",
    "不同目标半径下检出率随对比度的变化",
    "合成序列与真实视频的指标对比",
    "虚警抑制手段的尝试与结论",
    "候选截断配置对跟踪效果的影响",
    "软硬件各处理环节的耗时对比",
    "形态学方向的尺寸覆盖情况",
    "候选截断对尺寸覆盖的影响",
    "关键实测项汇总",
    "形态学方向与门限的召回—虚警权衡",
]

SUB_HEADS = ("功能与特性", "应用领域", "主要技术特点", "主要性能指标", "主要创新点",
             "设计流程", "整体介绍", "硬件系统介绍", "软件系统介绍",
             "可扩展之处", "心得体会")


def _ensure_style(doc, name, size, bold, center, east="黑体"):
    styles = doc.styles
    try:
        st = styles[name]
    except KeyError:
        st = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = styles["Normal"]
    st.font.size = Pt(size)
    st.font.bold = bold
    st.font.name = "Arial"
    rpr = st.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    rf.set(qn("w:eastAsia"), east)
    pf = st.paragraph_format
    if center:
        pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf.first_line_indent = Pt(0)
    return st


def _toc_para(instr, holder):
    p = OxmlElement("w:p")
    for kind, txt in (("begin", None), ("instr", instr), ("separate", None),
                      ("text", holder), ("end", None)):
        r = OxmlElement("w:r")
        if kind == "instr":
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = " %s " % txt
            r.append(el)
        elif kind == "text":
            t = OxmlElement("w:t")
            t.text = txt
            r.append(t)
        else:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
            r.append(el)
        p.append(r)
    return p


def _heading_para(doc, text):
    p = OxmlElement("w:p")
    ppr = OxmlElement("w:pPr")
    ps = OxmlElement("w:pStyle")
    ps.set(qn("w:val"), "2")          # Heading 2
    ppr.append(ps)
    p.append(ppr)
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    r.append(t)
    p.append(r)
    return p


def _pagebreak():
    p = OxmlElement("w:p")
    r = OxmlElement("w:r")
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    r.append(br)
    p.append(r)
    return p


def main(src=SRC, dst=DST):
    doc = Document(src)

    ch_st = _ensure_style(doc, "ChapterTitle", 14, True, False)
    fig_st = _ensure_style(doc, "FigCaption", 10, False, True)
    tab_st = _ensure_style(doc, "TableCaption", 10, False, True)

    # ① 章节标题：第X部分 + 1.x 小节
    pat_ch = re.compile(r"^第[一二三四五六七八九十]部分")
    n_ch = n_sub = 0
    for p in doc.paragraphs:
        t = p.text.strip()
        if pat_ch.match(t):
            p.style = ch_st
            n_ch += 1
        elif t in SUB_HEADS:
            p.style = ch_st
            n_sub += 1
    print("  章节标题 → ChapterTitle：%d 个第X部分 + %d 个小节" % (n_ch, n_sub))

    # ② 图题注（两个空格才是题注，单空格是说明文字）
    pat_cap = re.compile(r"^图\s*[\dA-Za-z]+\s{2}")
    n_fig = sum(1 for p in doc.paragraphs if pat_cap.match(p.text.strip()))
    for p in doc.paragraphs:
        if pat_cap.match(p.text.strip()):
            p.style = fig_st
    print("  图题注 → FigCaption：%d 个" % n_fig)

    # ③ 表题注：插在表格之前，用「紧邻表格」识别已有题注
    body = doc.element.body
    tbls = [c for c in body.iterchildren() if c.tag.split("}")[-1] == "tbl"]
    print("  表格：%d 个" % len(tbls))
    if len(tbls) == len(TABLE_TITLES):
        for i, (tbl, title) in enumerate(zip(tbls, TABLE_TITLES), 1):
            prev = tbl.getprevious()
            if prev is not None and prev.tag.split("}")[-1] == "p":
                para = Paragraph(prev, doc)
                if re.match(r"^表\s*\d+\s{2}", para.text.strip()):
                    para.style = tab_st
                    continue
            newp = OxmlElement("w:p")
            tbl.addprevious(newp)
            para = Paragraph(newp, doc)
            para.style = tab_st
            para.add_run("表 %d  %s" % (i, title)).font.size = Pt(10)
        print("  表题注 → TableCaption：%d 个" % len(tbls))
    else:
        print("  !! 表格数 %d 与标题数 %d 不符，跳过表题注" % (len(tbls), len(TABLE_TITLES)))

    # ④ 在「关键词」之后插入三份清单
    anchor = None
    for p in doc.paragraphs:
        if p.text.strip().startswith("关键词"):
            anchor = p._element
            break
    if anchor is None:
        print("  !! 未找到「关键词」段，未插入目录")
    else:
        blocks = [
            _pagebreak(),
            _heading_para(doc, "目录"),
            _toc_para(r'TOC \h \z \t "ChapterTitle,1"', "（更新域生成目录）"),
            _pagebreak(),
            _heading_para(doc, "图目录"),
            _toc_para(r'TOC \h \z \t "FigCaption,1"', "（更新域生成图目录）"),
            _pagebreak(),
            _heading_para(doc, "表目录"),
            _toc_para(r'TOC \h \z \t "TableCaption,1"', "（更新域生成表目录）"),
        ]
        cur = anchor
        for b in blocks:
            cur.addnext(b)
            cur = b
        print("  已插入「目录 / 图目录 / 表目录」三份清单")

    doc.save(dst)
    print("  已生成：%s（%.0f KB）" % (dst, os.path.getsize(dst) / 1024))
    print("  下一步：用 Word 更新域（Ctrl+A → F9）生成页码")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if len(a) > 0 else SRC, a[1] if len(a) > 1 else DST)
