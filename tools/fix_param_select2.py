import io
R = r"D:\firstharness\repo\pl\rtl"
def rd(p): return io.open(p, encoding="utf-8").read()
def wr(p, s): io.open(p, "w", encoding="utf-8", newline="\n").write(s)

p = R + r"\cfar_threshold_stream.v"; s = rd(p)
if "WIN_V" not in s:
    s = s.replace("WIN[5:0]", "WIN_V")
    s = s.replace("localparam HALF  = WIN / 2;", "localparam [5:0] WIN_V = WIN;   // Procise: parameter 不能位选\n    localparam HALF  = WIN / 2;")
    wr(p, s); print("cfar patched")

p = R + r"\ip2_pix_fifo.v"; s = rd(p)
if "DEPTH_V" not in s:
    s = s.replace("DEPTH[AW:0]", "DEPTH_V")
    key = "    parameter AW    = 9"
    i = s.index(key); j = s.index("\n", i)
    s = s[:j] + "\n    localparam [AW:0] DEPTH_V = DEPTH;   // Procise: parameter 不能位选" + s[j:]
    wr(p, s); print("pix_fifo patched")
print("ok")