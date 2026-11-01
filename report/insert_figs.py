# -*- coding: utf-8 -*-
"""
把插图插入报告 docx（v2：字符串级精确替换，不重排文档结构）

★ v1 的 bug：按段落拆分整个文档再重组，只保留 <w:p>，把表格 <w:tbl> 弄丢了。
★ v2 的做法：只在原文上把「指定占位段落」替换成「图片段落 + 图注段落」，
             其余内容（表格、样式、编号、页眉页脚）原样不动。
"""
import os
import re
import zipfile
from PIL import Image

ROOT = r"C:\Users\孔令浩1\Desktop\竞赛创新项目\嵌赛"
SRC_DOCX = r"D:\lowslow\out_report.docx"          # fill_report.py 的输出（含表格、无图）
IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figs")
OUT_DOCX = r"D:\lowslow\out_report_img.docx"

FONT = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="宋体" w:cs="Times New Roman"/>'
FONT_H = FONT[:-2] + ' w:hint="eastAsia"/>'
CONTENT_W_CM = 14.5
EMU_PER_CM = 360000

# 图号 -> (文件名, 图注)
FIGMAP = {
    "图 1": ("图1_系统整体框图.png", "图 1  系统整体框图（PS + PL + NPU 三级异构分工与数据流）"),
    "图 2": ("图2_硬件系统连接框图.png", "图 2  硬件系统连接框图（FMQL30TAI 异构平台与外围设备）"),
    "图 3": ("图3_整机装配示意.png",
              "图 3  整机装配示意（摄像头 / 主机板 / 上位机 / 电源的摆放与连线走向；板卡实物见图 4）"),
    "图 4": ("图4_硬件接口与连线图.png",
              "图 4  硬件接口与连线实拍（板载丝印可见：PS_UART / PS_ETH / PL_JTAG / PS_JTAG / 12V 电源 / RST 与 PL_KEY 按键 / SFP 与 PCIe 边缘连接器）"),
    "图 5": ("图5_软件处理流程图.png", "图 5  软件处理流程（7 个处理环节与 5 个关键数据接口）"),
    "图 6": ("图6_PL检测链路模块框图.png", "图 6  PL 检测链路模块框图（Black-Hat（MODE 可切，SE=21）→ CFAR → 候选提取；附方向修正与自抑制的实测结论）"),
    "图 7": ("图7_机械设计外壳切割图.png",
              "图 7  机械设计——亚克力外壳激光切割图（3 mm 板厚）：含开发板 100×100 轮廓、电源/网口/USB 三处开孔、前面板摄像头镜头孔 Ø14，以及 M3 铜柱与脚垫规格"),
    "图 8": ("图8_硬件连接特写.png",
              "图 8  硬件连接实拍——上沿连线区：SD 卡槽 / PS_UART / PS_ETH 千兆网口 / HDMI / 及右侧 12 V 电源输入（板载丝印已标注各接口）"),
    "图 9": ("图9_检测与跟踪效果.png", "图 9  软件基线实际运行效果（真实 720P；左：原始图；中：检测/跟踪叠加；右：二值化结果）"),
    "图 9b": ("图9b_NPU检测效果.png", "图 9b  NPU（ZG330 + YOLOv11n）检测效果：640×640 端到端推理，检测框经坐标反算回原图"),
    "图 10": ("图10_检出率曲线.png", "图 10  检出率随目标尺寸与对比度变化曲线（合成序列 9 组实测，CFAR k=4.0）"),
    "图 11": ("图11_PL仿真波形.png", "图 11  IP2 检测链路仿真波形（Verilog 仿真实测，三级流水线节拍）"),
    "图 12": ("图12_技术路线图.png", "图 12  系统技术路线（问题定义 → 三层异构分工 → 7 环节处理链路 → 关键设计决策与实测指标）"),
    "图 13": ("图13_帧率配置对比.png",
              "图 13  五种配置的帧率与耗时构成（同一硬件、同一位流实测；候选数放开到 47 后帧率跌至 7.9 fps）"),
    "图 14": ("图14_耗时分解.png",
              "图 14  端到端耗时分解（采集 32.2 / PL 13.8 / 跟踪 2.8 / 编码 12.9 ms；PL 仅占 22%，瓶颈在采集与编码）"),
    "图 15": ("图15_候选数与帧率.png",
              "图 15  候选数对帧率的影响与级联必要性（放开到 47 个候选时帧率 40.5→7.9 fps，且全部为虚警）"),
    "图 16": ("图16_尺寸覆盖矩阵.png",
              "图 16  软件多尺度的尺寸覆盖矩阵（四路降采样合并后覆盖 2~80 px，代价为单帧 10.6→13.8 ms）"),
    "图 17": ("图17_形态学方向权衡.png",
              "图 17  形态学方向与门限的召回—虚警权衡（100 张真实图 16 组配置；同召回下 Black-Hat 候选数低 3.7 倍）"),
}

NOPIC = {}



def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def run(text, color=None, size=None):
    rpr = FONT_H
    if color:
        rpr += '<w:color w:val="%s"/>' % color
    if size:
        rpr += '<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (size, size)
    return '<w:r><w:rPr>' + rpr + '</w:rPr><w:t xml:space="preserve">' + esc(text) + '</w:t></w:r>'


def img_para(rid, cx, cy, idx, name):
    return (
        '<w:p><w:pPr><w:spacing w:before="120" w:after="60"/><w:jc w:val="center"/></w:pPr>'
        '<w:r><w:drawing>'
        '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'distT="0" distB="0" distL="0" distR="0">'
        '<wp:extent cx="%d" cy="%d"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
        '<wp:docPr id="%d" name="%s"/>'
        '<wp:cNvGraphicFramePr xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:nvPicPr><pic:cNvPr id="%d" name="%s"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="%s"/>'
        '<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
        % (cx, cy, idx, name, idx, name, rid, cx, cy)
    )


def caption_para(text):
    return ('<w:p><w:pPr><w:pStyle w:val="12"/><w:spacing w:before="40" w:after="200" w:line="300" w:lineRule="auto"/>'
            '<w:ind w:left="0" w:firstLine="0" w:firstLineChars="0"/><w:jc w:val="center"/><w:rPr>' + FONT + '</w:rPr></w:pPr>'
            + run(text, color="404040", size=18) + '</w:p>')


def text_of(p):
    t = "".join(re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", p, re.S))
    return t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def main():
    zin = zipfile.ZipFile(SRC_DOCX)
    doc = zin.read("word/document.xml").decode("utf-8")
    rels = zin.read("word/_rels/document.xml.rels").decode("utf-8")

    # ---- ① 计算显示尺寸 + 注册关系 ----
    cx = int(CONTENT_W_CM * EMU_PER_CM)
    sizes, used = {}, set(re.findall(r'Id="([^"]+)"', rels))
    new_rels, new_media, rid_of = [], [], {}
    n = 100
    for i, key in enumerate(sorted(FIGMAP, key=lambda k: (int(re.search(r"(\d+)", k).group(1)), re.search(r"(\d+)([a-z]?)", k).group(2)))):
        fn, _ = FIGMAP[key]
        p = os.path.join(IMG_DIR, fn)
        if not os.path.exists(p):
            print("  !! 缺图片:", fn)
            continue
        im = Image.open(p)
        cy = int(cx * im.height / im.width)
        sizes[key] = (fn, cx, cy)
        while ("rId%d" % n) in used:
            n += 1
        rid = "rId%d" % n
        used.add(rid)
        target = "media/rpt_img%d.png" % (i + 1)
        rid_of[key] = (rid, target)
        new_rels.append('<Relationship Id="%s" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="%s"/>' % (rid, target))
        new_media.append((target, p))
        print("  %-6s %-32s %dx%d -> %.1f x %.1f cm" % (key, fn, im.width, im.height, cx / EMU_PER_CM, cy / EMU_PER_CM))

    rels_new = rels.replace("</Relationships>", "".join(new_rels) + "</Relationships>")

    # ---- ② 收集替换任务（字符串级，不重排文档）----
    jobs = []
    P = re.compile(r"<w:p\b(?:(?!<w:p\b).)*?</w:p>", re.S)
    for key in sorted(FIGMAP, key=lambda k: (-int(re.search(r"(\d+)", k).group(1)), re.search(r"(\d+)([a-z]?)", k).group(2))):
        m_ = re.search(r"(\d+)([a-z]?)", key)
        num, suf = int(m_.group(1)), m_.group(2)
        pat = re.compile(r"^【图\s*%d%s：" % (num, suf))
        for m in P.finditer(doc):
            p = m.group(0)
            if pat.match(text_of(p).strip()):
                rid, target = rid_of[key]
                _, cx2, cy2 = sizes[key]
                repl = img_para(rid, cx2, cy2, 500 + num * 2 + (1 if suf else 0), "rpt%d%s" % (num, suf)) + caption_para(FIGMAP[key][1])
                jobs.append((p, repl, key))
                print("  OK 插入 %s -> %s" % (key, FIGMAP[key][1][:34]))
                break
    for key in NOPIC:
        m_ = re.search(r"(\d+)([a-z]?)", key)
        num, suf = int(m_.group(1)), m_.group(2)
        pat = re.compile(r"^【图\s*%d%s：" % (num, suf))
        for m in P.finditer(doc):
            p = m.group(0)
            if pat.match(text_of(p).strip()):
                jobs.append((p, caption_para(NOPIC[key]), key))
                print("  -- 保留占位 %s" % key)
                break

    for p, repl, key in jobs:
        doc = doc.replace(p, repl, 1)

    # ---- ③ 打包（复制全部部件，只替换 document.xml 与 rels）----
    tmp = OUT_DOCX + ".new"
    for f in (OUT_DOCX, tmp):
        if os.path.exists(f):
            os.remove(f)
    zout = zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED)
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == "word/document.xml":
            data = doc.encode("utf-8")
        elif item.filename == "word/_rels/document.xml.rels":
            data = rels_new.encode("utf-8")
        zout.writestr(item, data)
    for target, path in new_media:
        zout.write(path, "word/" + target)
    zout.close()
    zin.close()
    os.replace(tmp, OUT_DOCX)

    print("")
    print("已生成:", OUT_DOCX)
    print("  插入图片: %d 张 | 保留占位: %d 处" % (len(jobs) - len(NOPIC), len(NOPIC)))
    print("  ★ 表格数（必须 > 0，否则结构被破坏）:", doc.count("<w:tbl>"))


if __name__ == "__main__":
    main()
