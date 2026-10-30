import io
p = r"D:\firstharness\repo\pl\rtl\ip2_pix_fifo.v"
s = io.open(p, encoding="utf-8").read()
bad = "\n    localparam [AW:0] DEPTH_V = DEPTH;   // Procise: parameter 不能位选"
s = s.replace(bad, "")
# 放进模块体内：紧跟端口表结束的 );
anchor = ");\n    reg  [7:0] mem"
if anchor in s:
    s = s.replace(anchor, ");\n    localparam [AW:0] DEPTH_V = DEPTH;   // Procise: parameter 不能位选\n    reg  [7:0] mem", 1)
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)
    print("fixed")
else:
    print("anchor not found")