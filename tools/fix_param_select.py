import io, re, os
R = r"D:\firstharness\repo\pl\rtl"

def rd(p):
    return io.open(p, encoding="utf-8").read()
def wr(p, s):
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)

# ---- win5.v ----
p = os.path.join(R, "win5.v"); s = rd(p)
if "DEPTH_V" not in s:
    anchor = "    localparam VPW"
    i = s.index(anchor)
    j = s.index("\n", i)
    ins = ("\n    // 2026-10-30 Procise 不接受对 parameter 做位选（W[PW-1:0]），改成定宽 localparam\n"
           "    localparam [PW-1:0]  DEPTH_V = DEPTH;\n"
           "    localparam [PW-1:0]  W_V     = W;\n"
           "    localparam [VPW-1:0] VD_V    = VD;\n"
           "    localparam [VPW-1:0] DELAY_V = DELAY;")
    s = s[:j] + ins + s[j:]
    s = s.replace("DEPTH[PW-1:0]", "DEPTH_V").replace("W[PW-1:0]", "W_V")
    s = s.replace("VD[VPW-1:0]", "VD_V").replace("DELAY[VPW-1:0]", "DELAY_V")
    wr(p, s); print("win5.v patched")

# ---- cfar_threshold_stream.v ----
p = os.path.join(R, "cfar_threshold_stream.v"); s = rd(p)
if "WIN_V" not in s:
    s2 = s.replace("WIN[5:0]", "WIN_V")
    m = re.search(r"^(\s*)localparam\s+WIN\b.*$", s2, re.M)
    if m:
        ins = "\n%s// Procise 不接受 parameter 位选，改定宽 localparam\n%slocalparam [5:0] WIN_V = WIN;" % (m.group(1), m.group(1))
        s2 = s2[:m.end()] + ins + s2[m.end():]
        wr(p, s2); print("cfar patched")

# ---- ip2_pix_fifo.v ----
p = os.path.join(R, "ip2_pix_fifo.v"); s = rd(p)
if "DEPTH_V" not in s:
    s2 = s.replace("DEPTH[AW:0]", "DEPTH_V")
    m = re.search(r"^(\s*)localparam\s+DEPTH\b.*$", s2, re.M)
    if m:
        ins = "\n%slocalparam [AW:0] DEPTH_V = DEPTH;" % m.group(1)
        s2 = s2[:m.end()] + ins + s2[m.end():]
        wr(p, s2); print("pix_fifo patched")

# ---- ip2_axi_top.v ----
p = os.path.join(R, "ip2_axi_top.v"); s = rd(p)
if "NPIX_V" not in s:
    s2 = s.replace("NPIX[31:0]", "NPIX_V")
    m = re.search(r"^(\s*)localparam\s+NPIX\b.*$", s2, re.M)
    if m:
        ins = "\n%slocalparam [31:0] NPIX_V = NPIX;" % m.group(1)
        s2 = s2[:m.end()] + ins + s2[m.end():]
        wr(p, s2); print("axi_top patched")
print("done")