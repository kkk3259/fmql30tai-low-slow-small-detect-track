# -*- coding: utf-8 -*-
"""
IP1（预处理模块）独立复核工具 —— S 的验收脚本

用途：按协作规范（docs/07 第 5 节"交叉复核"），独立验证 P 提交的 RTL 是否正确。
      不依赖板卡，只用开源仿真器 Icarus Verilog 跑一遍，再与"标准答案"逐像素比对。

做什么：
  ① 在临时目录跑 iverilog 编译 + vvp 仿真（不污染仓库里 P 提交的文件）
  ② 比对：我的仿真输出 vs P 的参考答案（ref.hex，OpenCV 生成）
  ③ 分开统计"内部像素 / 边界像素"，因为边界处理方式不同会有额外误差
  ④ 顺便比对：我的输出 vs P 提交的输出 → 验证可复现性

用法：
  python tools\\verify_ip1.py
  python tools\\verify_ip1.py --iverilog "C:\\iverilog\\bin"
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_HERE)

IV_DIR = r"D:\Programs\iverilog\bin"      # 默认安装位置，可用 --iverilog 覆盖
W_OUT = H_OUT = 16                        # 输出图尺寸（与 gen_stimulus.py 一致）


def read_hex(path):
    with open(path) as f:
        return [int(line.strip(), 16) for line in f if line.strip()]


def run_sim(iv_dir, sim_dir, tb, rtl, workdir):
    """在 workdir 里跑一次仿真，返回 output.hex 的路径"""
    iv = os.path.join(iv_dir, "iverilog.exe")
    vvp = os.path.join(iv_dir, "vvp.exe")
    for p in (iv, vvp):
        if not os.path.exists(p):
            raise SystemExit("找不到仿真器：" + p + "\n  提示：用 --iverilog 指定 bin 目录")

    shutil.copy(os.path.join(sim_dir, "input.hex"), os.path.join(workdir, "input.hex"))

    print("  ① 编译 iverilog ...")
    r1 = subprocess.run([iv, "-o", os.path.join(workdir, "tb.vvp"), tb, rtl],
                        cwd=workdir, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r1.returncode != 0:
        print(r1.stdout)
        print(r1.stderr)
        raise SystemExit("编译失败（returncode={}）".format(r1.returncode))
    print("     [OK] 编译通过")

    print("  ② 运行 vvp ...")
    r2 = subprocess.run([vvp, "tb.vvp"], cwd=workdir, capture_output=True, text=True, encoding="utf-8", errors="replace")
    for line in (r2.stdout or "").splitlines():
        if "收集到" in line or "finish" in line:
            print("     " + line.strip())
    out = os.path.join(workdir, "output.hex")
    if not os.path.exists(out):
        raise SystemExit("仿真没有产生 output.hex")
    return out


def compare(a, b, label, split=True):
    n = min(len(a), len(b))
    all_d = [abs(a[i] - b[i]) for i in range(n)]
    print("")
    print("  " + label)
    print("    像素数 {:>4} | 最大 {:>2} LSB | 平均 {:.3f} | 完全一致 {:>3}/{:<3} ({:.1f}%)".format(
        n, max(all_d), sum(all_d) / n, sum(d == 0 for d in all_d), n,
        100.0 * sum(d == 0 for d in all_d) / n))

    if split and n == W_OUT * H_OUT:
        inner, edge = [], []
        for i in range(n):
            y, x = divmod(i, W_OUT)
            (edge if (y == 0 or y == H_OUT - 1 or x == 0 or x == W_OUT - 1) else inner).append(all_d[i])
        print("      ├ 内部像素 {:>3} 个 | 最大 {:>2} LSB | 平均 {:.3f} | 一致率 {:.1f}%".format(
            len(inner), max(inner), sum(inner) / len(inner),
            100.0 * sum(d == 0 for d in inner) / len(inner)))
        print("      └ 边界像素 {:>3} 个 | 最大 {:>2} LSB | 平均 {:.3f} | 一致率 {:.1f}%".format(
            len(edge), max(edge), sum(edge) / len(edge),
            100.0 * sum(d == 0 for d in edge) / len(edge)))
        dist = Counter(all_d)
        print("      误差分布: " + ", ".join("{}LSB×{}".format(k, v) for k, v in sorted(dist.items())[:8]))
    return all_d


def main():
    ap = argparse.ArgumentParser(description="独立复核 IP1（iverilog 仿真 + 逐像素比对）")
    ap.add_argument("--iverilog", default=IV_DIR, help="iverilog 的 bin 目录")
    a = ap.parse_args()

    sim_dir = os.path.join(_PROJ, "pl", "sim")
    tb = os.path.join(_PROJ, "pl", "tb", "tb_preproc.v")
    rtl = os.path.join(_PROJ, "pl", "rtl", "preproc_axis.v")
    for p in (sim_dir, tb, rtl):
        if not os.path.exists(p):
            raise SystemExit("缺文件：" + p)

    print("")
    print("=== IP1 独立复核（S 的验收） ===")
    print("  被测模块: pl\\rtl\\preproc_axis.v")
    print("  Testbench: pl\\tb\\tb_preproc.v   （尺寸 %dx%d 输入 -> %dx%d 输出）"
          % (32, 32, W_OUT, H_OUT))
    print("")

    work = tempfile.mkdtemp(prefix="ip1check_")
    try:
        mine_path = run_sim(a.iverilog, sim_dir, tb, rtl, work)
        mine = read_hex(mine_path)
        ref = read_hex(os.path.join(sim_dir, "ref.hex"))
        his_path = os.path.join(sim_dir, "output.hex")
        his = read_hex(his_path) if os.path.exists(his_path) else []

        print("")
        print("=== 比对结果 ===")
        d1 = compare(mine, ref, "【A】我的仿真输出  vs  参考答案(ref.hex，OpenCV)")
        if his:
            d2 = compare(mine, his, "【B】我的仿真输出  vs  P 提交的输出(output.hex)", split=False)

        print("")
        print("=== 判定 ===")
        inner_max = 0
        if len(mine) == W_OUT * H_OUT:
            for i in range(len(mine)):
                y, x = divmod(i, W_OUT)
                if not (y == 0 or y == H_OUT - 1 or x == 0 or x == W_OUT - 1):
                    inner_max = max(inner_max, abs(mine[i] - ref[i]))
        print("  内部像素最大误差 : {} LSB   （规范要求 <= 2 LSB）-> {}".format(
            inner_max, "通过 [OK]" if inner_max <= 2 else "不通过 [FAIL]"))
        if his and max(d2) == 0:
            print("  可复现性         : 我跑的结果与提交的完全一致 [OK]")
        print("  边界像素          : 见上方统计（若明显偏大，说明边界模式与 OpenCV 不一致：")
        print("                      OpenCV GaussianBlur 默认 REFLECT_101，RTL 里是 clamp）")
        print("")
        print("  提示：仿真波形在临时目录 {} 里（tb.vcd），可用 GTKWave 打开".format(work))
        print("        D:\\Programs\\iverilog\\gtkwave\\bin\\gtkwave.exe  <vcd文件>")
    finally:
        pass    # 保留临时目录供看波形；如需清理可手动删


if __name__ == "__main__":
    main()
