import io, re
p = r"D:\firstharness\repo\pl\rtl\ip2_axi_top.v"
s = io.open(p, encoding="utf-8").read()
if "NPIX_AW" not in s:
    s = s.replace("NPIX[AW_F-1:0]", "NPIX_AW")
    m = re.search(r"^(\s*)localparam\s+\[31:0\]\s+NPIX_V\s*=\s*NPIX;.*$", s, re.M)
    if m:
        s = s[:m.end()] + "\n%s// Procise: parameter 不能位选\n%slocalparam [AW_F-1:0] NPIX_AW = NPIX;" % (m.group(1), m.group(1)) + s[m.end():]
        io.open(p, "w", encoding="utf-8", newline="\n").write(s)
        print("axi_top AW patched")
else:
    print("already")