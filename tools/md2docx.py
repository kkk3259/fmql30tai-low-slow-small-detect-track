# -*- coding: utf-8 -*-
"""Markdown → Word(.docx) 转换器（够用版，不依赖 pandoc）

支持：
  # / ## / ### 标题、**粗体**、`行内代码`、表格（含表头）、
  无序/有序列表、> 引用、--- 分隔线

用法：
    python tools/md2docx.py <输入.md> <输出.docx> [--title "文档标题"]
"""
import argparse
import os
import re
import sys

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

sys.stdout.reconfigure(encoding="utf-8")

CN_FONT = "宋体"
CN_BOLD = "黑体"
MONO_FONT = "Consolas"
ACCENT = RGBColor(0x1B, 0x3A, 0x5C)


def set_font(run, name=CN_FONT, size=None, bold=None, color=None):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def add_rich(par, text, base_size=10.5, base_font=CN_FONT):
    """把 **粗体** 与 `代码` 拆成多段 run"""
    # 先按 **...** 与 `...` 切分
    tokens = re.split(r"(\*\*.+?\*\*|`[^`]+`)", text)
    for tok in tokens:
        if not tok:
            continue
        if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
            r = par.add_run(tok[2:-2])
            set_font(r, CN_BOLD, base_size, True)
        elif tok.startswith("`") and tok.endswith("`") and len(tok) > 2:
            r = par.add_run(tok[1:-1])
            set_font(r, MONO_FONT, base_size - 0.5, color=RGBColor(0xB0, 0x3A, 0x2E))
        else:
            r = par.add_run(tok)
            set_font(r, base_font, base_size)


def is_table_sep(line):
    s = line.strip()
    if not s.startswith("|"):
        return False
    cells = [c for c in s.strip("|").split("|")]
    return all(re.fullmatch(r"\s*:?-{2,}:?\s*", c or "") for c in cells) and len(cells) > 0


def split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def convert(src, dst, title=None):
    lines = open(src, encoding="utf-8").read().splitlines()

    doc = Document()
    # 页面与默认样式
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Pt(56)
    st = doc.styles["Normal"]
    st.font.name = CN_FONT
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)

    if title:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(title)
        set_font(r, CN_BOLD, 18, True, ACCENT)
        p.paragraph_format.space_after = Pt(12)

    i = 0
    n_tables = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()

        # ---- 空行 ----
        if not s:
            i += 1
            continue

        # ---- 分隔线 ----
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", s):
            i += 1
            continue

        # ---- 表格 ----
        if s.startswith("|") and i + 1 < len(lines) and is_table_sep(lines[i + 1]):
            header = split_row(s)
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i].strip()))
                i += 1
            ncol = len(header)
            t = doc.add_table(rows=1, cols=ncol)
            t.style = "Table Grid"
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            for j, cell in enumerate(header):
                par = t.rows[0].cells[j].paragraphs[0]
                add_rich(par, "**%s**" % cell if cell else cell, 9.5)
                par.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for row in rows:
                cells = t.add_row().cells
                for j in range(ncol):
                    val = row[j] if j < len(row) else ""
                    par = cells[j].paragraphs[0]
                    add_rich(par, val, 9.5)
            doc.add_paragraph()
            n_tables += 1
            continue

        # ---- 标题 ----
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            level = len(m.group(1))
            txt = m.group(2).strip()
            p = doc.add_paragraph()
            sz = {1: 17, 2: 14.5, 3: 12.5, 4: 11.5}.get(level, 11)
            if level == 1:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(txt)
            set_font(r, CN_BOLD, sz, True, ACCENT)
            p.paragraph_format.space_before = Pt(10 if level <= 2 else 6)
            p.paragraph_format.space_after = Pt(5)
            i += 1
            continue

        # ---- 引用 ----
        if s.startswith(">"):
            body = re.sub(r"^>\s?", "", s)
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(18)
            add_rich(p, body, 9.5)
            for r in p.runs:
                r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
            i += 1
            continue

        # ---- 无序列表 ----
        m = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if m:
            indent = len(m.group(1)) // 2
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.left_indent = Pt(18 + indent * 14)
            add_rich(p, m.group(2))
            i += 1
            continue

        # ---- 有序列表 ----
        m = re.match(r"^(\s*)(\d+)[.)]\s+(.*)$", line)
        if m:
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.left_indent = Pt(18 + len(m.group(1)) // 2 * 14)
            add_rich(p, m.group(3))
            i += 1
            continue

        # ---- 普通段落 ----
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.25
        add_rich(p, s)
        i += 1

    doc.save(dst)
    return n_tables


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--title", default=None)
    a = ap.parse_args()

    if not os.path.exists(a.src):
        print("  ✗ 找不到: %s" % a.src)
        return 1
    n = convert(a.src, a.dst, a.title)
    print("  ✓ %s" % a.dst)
    print("    %.0f KB ｜ %d 个表格" % (os.path.getsize(a.dst) / 1024, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
