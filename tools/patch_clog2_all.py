import io, re

FILES = [
    r"D:\firstharness\repo\pl\rtl\win5.v",
    r"D:\firstharness\repo\pl\rtl\cfar_threshold_stream.v",
    r"D:\firstharness\repo\pl\rtl\candidate_extract_stream.v",
    r"D:\firstharness\repo\pl\rtl\ip2_pix_fifo.v",
    r"D:\firstharness\repo\pl\rtl\tophat_5x5_stream.v",
    r"D:\firstharness\repo\pl\rtl\ip2_top_stream.v",
]

# Full 1..32 bit ternary ladder. Must cover up to 2^31 because expressions like
# WIN*WIN*255*255 (= 6.2e8) need 30 bits. Whole ladder is parenthesised so that
# a trailing "+ 1" keeps the intended precedence.
def ladder(expr):
    parts = ["((%s)<=2)?1" % expr]
    for bits in range(2, 32):
        parts.append("((%s)<=%d)?%d" % (expr, 1 << bits, bits))
    return "(" + ":".join(parts) + ":32)"

pat = re.compile(r"\$clog2\s*\(\s*([^()]+?)\s*\)")

total = 0
for p in FILES:
    s = io.open(p, encoding="utf-8", errors="strict").read()
    n = len(pat.findall(s))
    if n == 0:
        print("  %-34s 0 (skip)" % p.split("\\")[-1])
        continue
    s2 = pat.sub(lambda m: ladder(m.group(1)), s)
    io.open(p, "w", encoding="utf-8", newline="\n").write(s2)
    print("  %-34s replaced %d, left %d" % (p.split("\\")[-1], n, len(pat.findall(s2))))
    total += n
print("total replaced:", total)
