# patch_addr6.py —— 把 AXI-Lite 地址改回 6 位（IP 包是 6 位），
# 兼容视图 0x18~0x38 保留，64 候选窗口改到 0x10（写=索引，读=数据）
import io

def rw(p):
    return io.open(p, encoding="utf-8").read()

def wr(p, s):
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)

# ---------- ip2_axi_top.v ----------
p = r"D:\firstharness\repo\pl\rtl\ip2_axi_top.v"
s = rw(p)

s = s.replace("input  wire [7:0]  s_axi_awaddr,", "input  wire [5:0]  s_axi_awaddr,")
s = s.replace("input  wire [7:0]  s_axi_araddr,", "input  wire [5:0]  s_axi_araddr,")
s = s.replace("reg  [7:0]  awaddr_l;", "reg  [5:0]  awaddr_l;")
s = s.replace("reg  [7:0]  araddr_l;", "reg  [5:0]  araddr_l;")
s = s.replace("awaddr_l    <= 8'd0;", "awaddr_l    <= 6'd0;")
s = s.replace("araddr_l   <= 8'd0;", "araddr_l   <= 6'd0;")
s = s.replace("case (awaddr_l[7:0])", "case (awaddr_l[5:0])")
s = s.replace("case (araddr_l[7:0])", "case (araddr_l[5:0])")

# 读通道：0x10 变成窗口数据；0x40/0x44 删除
s = s.replace("            8'h40:   s_axi_rdata <= {25'd0, cand_rd_idx};  // 写它选字\n"
              "            8'h44:   s_axi_rdata <= cand_rdata;            // 读该字\n", "")
s = s.replace("            8'h3C:   s_axi_rdata <= st_mirror;     // {done,err,14'd0,frame_id}",
              "            8'h3C:   s_axi_rdata <= st_mirror;     // {done,err,14'd0,frame_id}\n"
              "            6'h10:   s_axi_rdata <= cand_rdata;    // 64 候选窗口数据（写 0x10 选字）")

# 写通道：0x40 -> 0x10
s = s.replace("            8'h40: cand_rd_idx <= wdata_l[6:0];   // 候选表窗口索引（0x40，避开 0x18~0x3C 的兼容镜像）",
              "            6'h10: cand_rd_idx <= wdata_l[6:0];   // 候选表窗口索引（写 0x10，读 0x10 取该字）")
# 读通道里的 0x10 原本是 FRAME_ID，先删掉它，避免重复分支
s = s.replace("            8'h10:   s_axi_rdata <= frame_id;      // 帧号\n", "")

# 统一 8'hXX -> 6'hXX
import re
s = re.sub(r"8'h([0-9A-F]{2}):", lambda m: "6'h%s:" % m.group(1), s)
wr(p, s)
print("patched ip2_axi_top.v")

# ---------- ip2_axi_bd_wrap.v ----------
p2 = r"D:\firstharness\repo\pl\rtl\ip2_axi_bd_wrap.v"
s2 = rw(p2)
if "[7:0]  s_axi_awaddr" in s2:
    s2 = s2.replace("[7:0]  s_axi_awaddr", "[5:0]  s_axi_awaddr")
if "[7:0]  s_axi_araddr" in s2:
    s2 = s2.replace("[7:0]  s_axi_araddr", "[5:0]  s_axi_araddr")
s2 = s2.replace("ADDR_WIDTH 8", "ADDR_WIDTH 6")
s2 = s2.replace("ADDR_WIDTH 6", "ADDR_WIDTH 6")
wr(p2, s2)
print("patched ip2_axi_bd_wrap.v")
