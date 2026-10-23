# -*- coding: utf-8 -*-
"""逐帧比对：把视频逐帧喂给 Verilog 仿真（iverilog），与 Python 参考比对候选列表。
用法：
  python pl/tools/run_video_frames.py <视频路径> [--step 25] [--max 0] [--w 320 --h 180]
说明：
  - 每帧：缩放到 (w,h) → 跑 Python 参考(Top-Hat→CFAR(MAD)→CCL) → 写激励/参考
          → 跑 vvp 仿真 → 读输出 → 逐字段比对
  - 需要先编译好 tb_ip2_top_320.out（对应 w=320,h=180）
"""
import argparse
import os
import subprocess
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

SIM_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sim"))
VVP = r"C:\iverilog\bin\vvp.exe"
VVP_OUT = os.path.join(SIM_DIR, "tb_ip2_top.out")       # 128x72 测试台
IN_HEX = os.path.join(SIM_DIR, "input_integration.hex")
REF_HEX = os.path.join(SIM_DIR, "ref_integration.hex")
OUT_HEX = os.path.join(SIM_DIR, "output_integration.hex")


def ref_chain(gray):
    """Top-Hat -> CFAR(MAD+积分图) -> CCL，返回候选列表 [(x,y,area,peak)]"""
    H, W = gray.shape
    yy, xx = np.mgrid[0:H, 0:W].astype(np.int32)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
    # ---- CFAR：真实标准差（与 cfar_threshold_stream.v 同一整数判决）----
    from gen_cfar_std_ref import cfar_std
    binary = cfar_std(th.reshape(-1).astype(np.int64), W, H)[0].astype(np.uint8) * 255
    n, lab, stats, cents = cv2.connectedComponentsWithStats(binary, connectivity=8)
    cands = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 2 or area > 200:
            continue
        m = (lab == i)
        sum_x = int(np.sum(xx[m])); sum_y = int(np.sum(yy[m]))
        area = int(m.sum()); peak = int(th[m].max())
        cands.append(((sum_x + area // 2) // area, (sum_y + area // 2) // area, area, peak))
    cands.sort(key=lambda c: -c[3])
    return cands[:5]


def w_cand(cands):
    out = [len(cands)]
    for i in range(5):
        if i < len(cands):
            x, y, a, p = cands[i]
            out += [x >> 8, x & 255, y >> 8, y & 255, a >> 8, a & 255, p]
        else:
            out += [0] * 7
    return out


def write_hex(path, vals):
    with open(path, "w") as f:
        for v in vals:
            f.write("%02X\n" % v)


def read_hex(path):
    return [int(x, 16) for x in open(path).read().split()]


def canon(b):
    """解析 36 字节列表并按 (peak 降, x 升, y 升) 规范排序，消除同 peak 的并列顺序差异"""
    n = b[0]
    c = []
    for i in range(n):
        x = (b[1 + i * 7] << 8) | b[2 + i * 7]
        y = (b[3 + i * 7] << 8) | b[4 + i * 7]
        a = (b[5 + i * 7] << 8) | b[6 + i * 7]
        p = b[7 + i * 7]
        c.append((x, y, a, p))
    return sorted(c, key=lambda t: (-t[3], t[0], t[1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--w", type=int, default=128)
    ap.add_argument("--h", type=int, default=72)
    ap.add_argument("--step", type=int, default=25, help="每 N 帧取 1 帧")
    ap.add_argument("--max", type=int, default=0, help="最多处理帧数，0=全部")
    a = ap.parse_args()

    if not os.path.exists(VVP_OUT):
        sys.exit("缺少 %s，请先编译 tb_ip2_top_320.out" % VVP_OUT)

    cap = cv2.VideoCapture(a.video)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print("视频: %s | 共 %d 帧 | 测试分辨率 %dx%d | 每 %d 帧取 1 帧" %
          (a.video, total, a.w, a.h, a.step))

    matched = 0
    processed = 0
    frames = list(range(0, total, a.step))
    if a.max:
        frames = frames[:a.max]

    for fi, fid in enumerate(frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, fid)
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (a.w, a.h),
                          interpolation=cv2.INTER_AREA)

        cands = ref_chain(gray)
        ref = w_cand(cands)
        write_hex(IN_HEX, [int(v) for v in gray.ravel()])
        write_hex(REF_HEX, ref)

        r = subprocess.run([VVP, VVP_OUT], cwd=SIM_DIR, stdout=subprocess.DEVNULL)
        if r.returncode != 0:
            print("帧 %d: vvp 失败(退出码 %d)" % (fid, r.returncode))
            continue

        out = read_hex(OUT_HEX)
        ok = (canon(out) == canon(ref))
        matched += ok
        processed += 1
        # 打印候选（坐标缩放到原视频分辨率 = 测试坐标 × (1080/320)）
        sx = 1920 / a.w
        sy = 1080 / a.h
        cand_str = " ".join("(%d,%d p%d)" % (int(x * sx), int(y * sy), p) for x, y, a, p in cands)
        print("帧 %4d [%2d/%2d] %s  参考候选=%d: %s" %
              (fid, fi + 1, len(frames), "✅" if ok else "❌", len(cands), cand_str))

    cap.release()
    print("\n===== 逐帧比对结果 =====")
    print("处理帧数: %d | 一致: %d | 不一致: %d | 一致率: %.1f%%" %
          (processed, matched, processed - matched, 100.0 * matched / max(processed, 1)))


if __name__ == "__main__":
    main()
