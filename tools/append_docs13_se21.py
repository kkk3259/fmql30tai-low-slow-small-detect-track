# -*- coding: utf-8 -*-
# append_docs13_se21.py —— 给 docs/13 追加“SE=21 上板验收”小节
import io

p = r"D:\firstharness\repo\docs\13-PL上板进展与卡点.md"
s = io.open(p, encoding="utf-8").read()

add = u"""

## 13. SE=21 结构元上板验收（2026-10-28 深夜）

### 13.1 位流与资源

| 项目 | 数值 |
|---|---|
| 位流 | `ip2_bd_wrapper.bit` 2026-10-28 23:10:04，5,980,026 B |
| 时序 | WNS **+1.444 ns** / TNS 0 / 保持 WHS +0.055 ns（50 MHz） |
| LUT | 51,039 / 78,600 = **64.9%** |
| LUTRAM | 14,807 / 26,600 = **55.7%** |
| BRAM | 64 / 265（全部是像素 FIFO） |
| FF | 17,698 |

关键改动：`win5.v` 的 441 项线性归约改成 `minmax_tree.v` 的平衡树（6 级），
时序从 **WNS −7.775 ns** 修到 **+1.444 ns**。

### 13.2 位流加载的正确姿势（踩过两次坑）

1. 必须用 Vivado 的**无头 .bin**：`write_bitstream -force -bin_file <名字>.bit`
   → 同时产生 `<名字>.bit`（5,980,026 B，带文本头）和 `<名字>.bin`（5,979,916 B，无头）。
2. 再对 `.bin` 做 **32 位字内字节交换**（首 4 字节仍是 `FF FF FF FF`）。
   交换后的 md5 本次为 `c28a56816b57036cbecbfa55906499ea`。
3. 写 `/sys/class/fpga_manager/fpga0/firmware` 之前**必须先停掉 PS 侧应用**
   （`pkill -f cam_pipe`）。带着活跃的 AXI 事务重配 PL 会把板子挂死（实测一次）。
4. 失败症状与含义：
   - `could not find a sync word` → 文件不是"无头+交换"的 bin（把 .bit 直接交换就会这样）；
   - `state = write init error` → 上一条的后果，PL 处于未配置状态；
   - 挂死（ping 不通）→ 需要按 RST_POR 或重新上电。

### 13.3 检出范围实测（probe64.py，10 个合成目标）

`STATUS = 0x00010A02`，`n_cand = 10`，`用时 10.4 ms`，**命中 10/10，VERDICT CAND64-OK**：

| 目标边长 | 检出面积 | 期望面积 |
|---|---|---|
| 2×2 | 4 | 4 |
| 3×3 | 9 | 9 |
| 4×4 | 16 | 16 |
| 5×5 | 25 | 25 |
| 6×6 | 36 | 36 |
| 7×7 | 49 | 49 |

面积与真实亮块面积**逐一相等**，坐标也全对。对比 SE=5 时只能检 1~4 px、
5 px 以上全丢 —— 这就是"比赛目标 15~70 px 看不见"的直接原因。

### 13.4 实时链路

`cam_pipe.py` 恢复后：`fps 28.7~29.1`、`PL 10.23 ms`（与 SE=5 版本持平，SE 加大没有掉帧）。
当前场景（夜间天花板/窗户）`n_cand = 0`：大面积过曝区被面积上限（200）滤掉，属预期行为。

### 13.5 遗留

- 画面清晰度：夜间 `exposure_auto_priority` 会让驱动降帧换长曝光（运动模糊），
  `v4l2-ctl --set-ctrl exposure_auto_priority=0` 可强制 30 fps；
- 识别准确率：CFAR 判决门限（K=4/FLOOR=3）、面积区间（2~200）、Top-Hat 结构元
  三者需要一起调，建议用真实录像离线回放标定；
- HDMI 输出：官方 `rtl/display/uihdmitx.v` 可直接复用（720p60，引脚已核对），
  但需要并入 BD 并跑 742.5 MHz 的 serdes，单独排期。
"""

if u"## 13. SE=21 结构元上板验收" in s:
    print("已存在，跳过")
else:
    io.open(p, "w", encoding="utf-8").write(s + add)
    print("已追加，文件行数:", (s + add).count("\n") + 1)
