import io

p = r"D:\firstharness\repo\pl\rtl\win5.v"
s = io.open(p, encoding="utf-8", errors="strict").read()

ladder_d = ("(DEPTH<=2)?1:(DEPTH<=4)?2:(DEPTH<=8)?3:(DEPTH<=16)?4:(DEPTH<=32)?5:"
            "(DEPTH<=64)?6:(DEPTH<=128)?7:(DEPTH<=256)?8:(DEPTH<=512)?9:"
            "(DEPTH<=1024)?10:(DEPTH<=2048)?11:(DEPTH<=4096)?12:(DEPTH<=8192)?13:14")
ladder_v = ("(VD<=2)?1:(VD<=4)?2:(VD<=8)?3:(VD<=16)?4:(VD<=32)?5:"
            "(VD<=64)?6:(VD<=128)?7:(VD<=256)?8:(VD<=512)?9:"
            "(VD<=1024)?10:(VD<=2048)?11:(VD<=4096)?12:(VD<=8192)?13:(VD<=16384)?14:15")

old_pw = "localparam PW    = $clog2(DEPTH);"
new_pw = ("// Procise elaborate rejects the clog2 system function; explicit ternary ladder.\n"
          "    localparam PW    = " + ladder_d + ";")
old_vp = "localparam VPW   = $clog2(VD);"
new_vp = ("localparam VPW   = " + ladder_v + ";")

assert old_pw in s, "PW line not found"
assert old_vp in s, "VPW line not found"
s = s.replace(old_pw, new_pw).replace(old_vp, new_vp)
assert "$clog2(" not in s, "clog2 call still present"
io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("patched win5.v OK; clog2 call count now:", s.count("$clog2("))
