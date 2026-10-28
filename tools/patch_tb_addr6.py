# patch_tb_addr6.py —— tb 里的候选窗口地址改到 0x10，并去掉与索引冲突的 frame_id 写
import io, re
p = r"D:\firstharness\repo\pl\tb\tb_axi_top.v"
s = io.open(p, encoding="utf-8").read()
s = s.replace("axi_write(6'h10, 32'h0000_0001);   // frame_id = 1\n", "")
s = s.replace("axi_write(8'h40, wi[31:0]);", "axi_write(6'h10, wi[31:0]);")
s = s.replace("axi_read (8'h44, wd);", "axi_read (6'h10, wd);")
for i in range(4):
    s = s.replace("axi_write(8'h40, 32'd%d); axi_read(8'h44, w%d);" % (i, i),
                  "axi_write(6'h10, 32'd%d); axi_read(6'h10, w%d);" % (i, i))
io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("tb patched")

# probe64.py：窗口地址 0x40/0x44 -> 0x10
q = r"D:\firstharness\repo\ps\probe64.py"
t = io.open(q, encoding="utf-8").read()
t = t.replace("R_CIDX = 0x40", "R_CIDX = 0x10")
t = t.replace("R_CDAT = 0x44", "R_CDAT = 0x10")
t = t.replace('(st >> 10) & 0xFF', '(st >> 8) & 0xFF')
io.open(q, "w", encoding="utf-8", newline="\n").write(t)
print("probe64 patched")
