import io
p = r"D:\firstharness\repo\pl\rtl\ip2_axi_top.v"
s = io.open(p, encoding="utf-8").read()
s = s.replace("NPIX_AW", "NPIX")
# 删掉多余的 NPIX_AW 声明行（已被替换成 NPIX，会变成重复声明）
out = []
for ln in s.split("\n"):
    if "localparam [AW_F-1:0] NPIX = NPIX;" in ln:
        continue
    if ln.strip() == "// Procise: parameter 不能位选" and "NPIX" in "\n".join(out[-3:]):
        continue
    out.append(ln)
s2 = "\n".join(out)
io.open(p, "w", encoding="utf-8", newline="\n").write(s2)
print("ok")