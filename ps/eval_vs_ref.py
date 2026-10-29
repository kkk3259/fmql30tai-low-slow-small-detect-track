# eval_vs_ref.py —— 真实相机帧上：PL 结果 vs Python 参考模型（同帧、同参数）的定量评估
# 用法（板上）：python3 eval_vs_ref.py [帧数]
# 退出前会打印：逐帧明细 + 汇总（召回/虚警/重合率）
import sys, time
sys.path.insert(0, "/root/ip2")
import numpy as np
import cv2

W, H = 640, 360

def ref_detect(gray):
    """Python 参考：Top-Hat(21x21) -> CFAR(31x31, K=1, FLOOR=3) -> 连通域(area 2..2047) -> 质心"""
    k21 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k21)
    f = th.astype(np.float32)
    m = cv2.blur(f, (31, 31))
    sd = np.sqrt(np.maximum(cv2.blur(f * f, (31, 31)) - m * m, 0.0))
    det = ((f > (m + 1.0 * sd + 3.0)).astype(np.uint8)) * 255
    n, lab, stats, cent = cv2.connectedComponentsWithStats(det, 8)
    out = []
    for i in range(1, n):
        a = int(stats[i][4])
        if 2 <= a <= 2047:
            out.append((int(cent[i][0]), int(cent[i][1]), a))
    return out

def main():
    nfrm = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    from cam_pipe import HW
    hw = HW()
    print("VERSION=0x%08x" % hw.rd(0x14))
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    tol = 6
    tot_ref = tot_pl = tot_hit = tot_fp = 0
    print("%-4s %-6s %-6s %-6s %-6s %-8s" % ("帧", "参考", "PL", "命中", "虚警", "PL耗时ms"))
    for i in range(nfrm):
        ok, fr = cap.read()
        if not ok:
            continue
        if fr.shape[0] > H:
            top = (fr.shape[0] - H) // 2
            fr = fr[top:top + H, :, :]
        gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        ref = ref_detect(gray)
        st, pl, dt = hw.run(gray)
        hit = 0
        for rx, ry, ra in ref:
            for c in pl:
                if abs(int(c["x"]) - rx) <= tol and abs(int(c["y"]) - ry) <= tol:
                    hit += 1
                    break
        fp = 0
        for c in pl:
            m = False
            for rx, ry, ra in ref:
                if abs(int(c["x"]) - rx) <= tol and abs(int(c["y"]) - ry) <= tol:
                    m = True
                    break
            if not m:
                fp += 1
        tot_ref += len(ref); tot_pl += len(pl); tot_hit += hit; tot_fp += fp
        print("%-4d %-6d %-6d %-6d %-6d %-8.1f" % (i, len(ref), len(pl), hit, fp, dt))
    cap.release()
    rec = 100.0 * tot_hit / max(tot_ref, 1)
    prec = 100.0 * (tot_pl - tot_fp) / max(tot_pl, 1)
    print()
    print("=== 汇总（%d 帧，容差 %d px）===" % (nfrm, tol))
    print("参考目标总数 %d，PL 候选总数 %d" % (tot_ref, tot_pl))
    print("召回率 %.1f%%（%d/%d）" % (rec, tot_hit, tot_ref))
    print("精确率 %.1f%%（虚警 %d）" % (prec, tot_fp))

if __name__ == "__main__":
    main()
