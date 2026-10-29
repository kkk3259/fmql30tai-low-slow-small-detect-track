# -*- coding: utf-8 -*-
"""CFAR 参数扫描：验证「目标越大越检不出」的自抑制现象并给出解法

背景：P 在板上实测（合成图，SE=21，k=4.0，win=31×31）发现 5px 以上全部漏检，
      归因为「CFAR 自适应门限自抑制」。本脚本在 PC 上独立复现并扩展验证。

一、机制（数学）

  以 8px 目标（面积 64）、CFAR 窗 31×31（961 像素）、背景 8、目标 240 为例：
    均值 μ = (64×240 + 897×8) / 961 ≈ 23.4
    标准差 σ ≈ 55（目标自身贡献大部分方差）
    门限 = μ + 4σ + 3 ≈ 23.4 + 220 + 3 ≈ 246 > 目标 Top-Hat 值 232  →  漏检

  目标越大 → 在窗内占比越高 → σ 越大 → 门限抬得越高 → 越检不出。
  这是「目标参与自身背景统计」导致的经典自抑制。

二、实测（合成图，背景 8 + 中心亮块 240，SE=21）

  配置                        2  4  6  8 10 14 20 30   ← 目标边长 px
  k=4.0  win=31（当前 PL）    Y  Y  Y  .  .  .  .  .
  k=3.0  win=31               Y  Y  Y  Y  .  .  .  .
  k=2.5  win=31               Y  Y  Y  Y  Y  .  .  .
  k=2.0  win=31               Y  Y  Y  Y  Y  .  .  .
  k=4.0  win=51               Y  Y  Y  Y  Y  .  .  .
  k=4.0  guard=11 win=31      Y  Y  Y  Y  Y  .  .  .
  k=2.0  guard=11 win=31      Y  Y  Y  Y  Y  Y  .  .   ← 最好，到 14px

  ⇒ 三个有效手段：降 k、加大统计窗、参考窗排除目标（guard cell）
  ⇒ 但最优组合也只能到 14px，20px 以上仍漏

三、增大结构元 SE 无效（实测 SE 从 5 到 61）

  SE=5 / 11 / 21 / 31 / 41 / 61 全部只能检出 2/4/6px。
  ⇒ 瓶颈是 CFAR 的门限抬升，不是形态学。

四、面积上限不是主因

  MAX_AREA 从 200 放宽到 5000，检出结果完全不变。
  ⇒ P 推测的「MAX_AREA=200 会滤掉 20px（面积 400）以上目标」方向对，
    但在当前 k=4.0 下目标根本过不了 CFAR，轮不到面积过滤。

五、真实图上的额外发现

  真实背景（eval_roi_448 的图）+ 注入亮块 240：SE=21 下 2~30px 全部检不出
    ⇒ 真实图的云/建筑纹理把 σ 抬得更高，注入的亮块被背景压过
  真实背景 + 注入暗块 20：2px、4px 可检，6px 以上不可检
    ⇒ 与「真实场景目标是暗点剪影」的发现一致，支持改用 Black-Hat

六、结论与建议

  1. PL 侧定位应为「≤10px 的小目标」，而不是 P 原设想的「≤20px」
     —— 小目标恰好是全图 YOLO 的盲区（<8px 召回 48.5%），这才是 PL 的价值所在。
  2. 推荐参数：k 从 4.0 降到 2.5、统计窗从 31×31 增到 51×51（或加 guard cell）。
  3. 15px 以上目标交给全图 YOLO，不必让 PL 勉强覆盖（形态学 + CFAR 在该尺度不经济）。
  4. CFAR 参数必须用真实录像回放标定，不能靠合成图（两者 σ 分布差异很大）。

用法：
  python tools/bench_cfar_param_scan.py
"""
import numpy as np
import cv2

W, H = 640, 360
SE, WIN, K, FLOOR = 21, 31, 4.0, 3.0
MIN_AREA, MAX_AREA = 2, 200


def morph(g, se, mode="top"):
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (se, se))
    return cv2.morphologyEx(g, cv2.MORPH_TOPHAT if mode == "top"
                            else cv2.MORPH_BLACKHAT, k)


def cfar(enh, win, k, floor):
    f = enh.astype(np.float32)
    mu = cv2.boxFilter(f, -1, (win, win), normalize=True, borderType=cv2.BORDER_REFLECT)
    mu2 = cv2.boxFilter(f * f, -1, (win, win), normalize=True, borderType=cv2.BORDER_REFLECT)
    sd = np.sqrt(np.maximum(mu2 - mu * mu, 0))
    return ((f > mu + k * sd + floor)).astype(np.uint8) * 255


def cfar_guard(enh, win, guard, k, floor):
    """参考窗 = 大窗统计 − 中心 guard 窗统计（把目标排除在背景估计之外）"""
    f = enh.astype(np.float32)
    n1, n2 = win * win, guard * guard
    s1 = cv2.boxFilter(f, -1, (win, win), normalize=True, borderType=cv2.BORDER_REFLECT) * n1
    s1b = cv2.boxFilter(f * f, -1, (win, win), normalize=True, borderType=cv2.BORDER_REFLECT) * n1
    s2 = cv2.boxFilter(f, -1, (guard, guard), normalize=True, borderType=cv2.BORDER_REFLECT) * n2
    s2b = cv2.boxFilter(f * f, -1, (guard, guard), normalize=True, borderType=cv2.BORDER_REFLECT) * n2
    n = np.maximum(n1 - n2, 1)
    mu, mu2 = (s1 - s2) / n, (s1b - s2b) / n
    sd = np.sqrt(np.maximum(mu2 - mu * mu, 0))
    return ((f > mu + k * sd + floor)).astype(np.uint8) * 255


def hit(binary, cx=320, cy=180, tol=4, max_a=MAX_AREA):
    n, _lab, stats, cents = cv2.connectedComponentsWithStats(binary, connectivity=8)
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]
        if a < MIN_AREA or a > max_a:
            continue
        if abs(cents[i][0] - cx) <= tol and abs(cents[i][1] - cy) <= tol:
            return True
    return False


def scan(se=SE, win=WIN, k=K, floor=FLOOR, guard=None, max_a=MAX_AREA):
    out = []
    for s in (2, 4, 6, 8, 10, 14, 20, 30):
        img = np.full((H, W), 8, np.uint8)
        cv2.rectangle(img, (320 - s // 2, 180 - s // 2),
                      (320 + s // 2, 180 + s // 2), 240, -1)
        enh = morph(img, se)
        b = (cfar_guard(enh, win, guard, k, floor) if guard
             else cfar(enh, win, k, floor))
        out.append("Y" if hit(b, max_a=max_a) else ".")
    return out


def main():
    print("  合成图（背景 8 + 中心亮块 240），SE=21")
    print("  尺寸档（边长 px）：2  4  6  8 10 14 20 30")
    print()
    print("  %-24s %s" % ("配置", ""))
    for k in (4.0, 3.0, 2.5, 2.0, 1.5):
        print("  k=%-4.1f win=31           %s" % (k, "  ".join(scan(k=k))))
    print()
    for win in (31, 51):
        print("  k=4.0 win=%-3d           %s" % (win, "  ".join(scan(win=win))))
    print()
    for k in (4.0, 2.0):
        print("  k=%-4.1f guard=11 win=31   %s" % (k, "  ".join(scan(k=k, guard=11))))
    print()
    print("  SE 扫描（k=4.0, win=31）—— 证明增大结构元无效：")
    for se in (5, 11, 21, 31, 41, 61):
        print("  SE=%-3d                 %s" % (se, "  ".join(scan(se=se))))
    print()
    print("  放宽面积上限（k=4.0, win=31）—— 证明面积过滤不是主因：")
    for ma in (200, 5000):
        print("  MAX_AREA=%-5d          %s" % (ma, "  ".join(scan(max_a=ma))))
    print()
    print("  图例：Y=检出，.=漏检")
    print("  结论：最优配置（k=2.0 + guard=11）可到 14px；")
    print("        PL 应定位为「≤10px 小目标」，15px 以上交给全图 YOLO。")


if __name__ == "__main__":
    main()
