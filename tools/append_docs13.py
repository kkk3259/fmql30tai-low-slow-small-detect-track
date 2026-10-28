# -*- coding: utf-8 -*-
# append_docs13.py —— 给 docs/13 追加“十二、2026-10-28 深夜”一节（UTF-8 安全）
import io

p = r"D:\firstharness\repo\docs\13-PL上板进展与卡点.md"
sec = u"""
---

## 十二、2026-10-28 深夜：结构元参数化 21×21（能看 ≤20px 目标）+ 时序修复

### 12.1 为什么要改结构元

Top-Hat 的"结构元"（腐蚀/膨胀的窗口）决定了它能看见多大的目标：**开运算会抹掉比窗口小的亮块**，
所以 Top-Hat 只能输出"比结构元小"的目标。原来的 5×5 只能检 1~4 px，而比赛目标是 15~70 px，
等于**完全看不见**。靶图实测（`D:\\firstharness\\dl\\ip2_target.png`，3/6/10/20/30 px 白方块）：

| 目标边长 | 5×5 检出 | area |
|---|---|---|
| 2 px | ✅ | 4 |
| 3 px | ✅ | 9 |
| 4 px | ✅ | 16 |
| 5 px 及以上 | ❌ | — |

所以结构元改成 **21×21**（可检 ≤20 px），并把 SE 做成参数贯穿整条链：
`ip2_axi_top` → `ip2_top_stream` → `tophat_5x5_stream` → 两个 `win5`（腐蚀/膨胀）。

### 12.2 参数化踩的两个坑（都已修，且用"新旧逐样本对比"验证）

1. **行间归约漏了第 0 行**：`vc[0]` 误取成 `hc[SE*SE-1]`（最后一行第 0 列），应为 `hc[SE-1]`。
2. **valid 延迟线必须按 `o_ready` 自由移位**（不能按 `i_valid & i_ready` 门控），
   否则参数化后数据与 valid 相位差 1 个样本。

验证方法：从 git HEAD 取出旧版改名为 `win5_old`，写 `synth/equiv/tb_win5_cmp.v` +
`tb_tophat_stream_128.v` 逐拍对比，用 `synth/equiv/cmp_shift2.py` 做平移搜索。
最终 **SE=5 时 `diffs=0 / shift=0`** —— 参数化没有破坏原有行为。

### 12.3 时序：441 级线性比较链 → 平衡树

第一版 SE=21 综合出来 **WNS = −7.775 ns @50 MHz**（`ip2_bd_i/ip2_0/inst/u_ip2/u_chain/u_tophat/u_erode/tap_reg[43][2]`
→ `o_data_r_reg`，60 级逻辑）。原因是归约写成了线性链
`hc[i] = min(hc[i-1], tap[i])`：441 个抽头就是 441 级串联比较。

修法：新增 `repo/pl/rtl/minmax_tree.v`（平衡树，逐级两两归约），win5 里每行一棵树、
行结果再一棵树 → 深度从 441 级降到约 10 级。修完重建：

| 指标 | 线性链版 | 平衡树版 |
|---|---|---|
| WNS | **−7.775 ns** | **+1.444 ns** ✅ |
| TNS | −115.067 ns | 0.000 |
| 失败端点 | 16 | 0 |
| Slice LUTs | 51,039 / 78,600（64.94%） | 同上量级 |
| LUT as Memory | 14,807 / 26,600（55.67%） | — |
| Block RAM | 64 / 265 | — |
| FF | 17,698（11.26%） | — |

位流：`synth/vivado/ip2_ps4/ip2_ps.runs/impl_1/ip2_bd_wrapper.bit`（2026-10-28 23:10:04，5,980,026 B）。

### 12.4 寄存器映射（8051 也要照这个改）

地址宽度从 6 位扩到 8 位（否则 `0x40` 会回卷成 `0x00`）：

| 偏移 | 读 | 写 |
|---|---|---|
| `0x00` | — | bit0 = start |
| `0x04` / `0x08` | FRAME_ADDR / RESULT_ADDR | 同 |
| `0x0C` | `{frm_cnt[15:8], n_cand[7:0], -, err, done, busy}` | — |
| `0x10` | FRAME_ID | FRAME_ID |
| `0x14` | VERSION = 0x00010000 | — |
| `0x18~0x38` | **36 字节兼容视图**（9 个字，S 的 `web_console.py` 就按这个读） | — |
| `0x3C` | 状态字镜像 | — |
| `0x40` | 窗口索引（读回当前索引） | 窗口索引 0~112 |
| `0x44` | 该索引对应的 32 位字 | — |

窗口共 113 个字 = 452 字节 = `n_cand`(1) + 64×(7 字节候选)。
PS 侧读取顺序：先读 `0x18~0x38` 拿 `n_cand` 和前 5 个候选；若 `n_cand > 5` 再走 `0x40/0x44` 把 64 个全读出来。

### 12.5 烧位流的正确姿势（重要事故记录）

- 必须用 Vivado `write_bitstream -bin_file` 生成的**无头 `.bin`**，再按 32 位字**字节交换**；
  交换后前 4 字节应为 `FF FF FF FF`。
  踩坑：拿 `.bit` 自己剥文本头再交换，在某些构建上会剥错（实测前 16 字节变成 ASCII 垃圾），
  烧进去 `fpga_manager` 直接报 `Invalid bitstream, could not find a sync word`。
- **重配置前必须先停掉正在跑的应用**（`pkill -f cam_pipe`），否则 PS 侧还有未完成的 AXI 事务，
  PL 一重配就把 PS 总线挂死 —— 实测：写完 `firmware` 后板子直接失联（ping 不通、SSH 超时），
  只能按 **RST_POR** 或断电重启。
- 远程烧写脚本：`D:\\firstharness\\synth\\flash_bit.ps1 -Bin <无头.bin>`（会自动交换字节、
  停应用、上传、自加载；前 4 字节不是 `FF FF FF FF` 就拒绝烧）。

### 12.6 当前状态（2026-10-28 23:30）

- 新位流（SE=21 + 64 候选 + 8 位地址 + 平衡树归约）已生成、时序达标、字节交换后已上传到板子
  `/lib/firmware/ip2_bd_wrapper.bin`（md5 `c28a56816b57036cbecbfa55906499ea`）。
- 但**重配置时板子挂死了**（见 12.5 第 3 条），需要人工按一次 **RST_POR**（或断电重启）。
- 上电后 `/etc/init.d/ip2demo` 会自动加载这个新位流并起服务，所以**重启后就是新版本**。

**早上恢复后的验证清单**（三分钟）：

```bash
# 1) 板子起来后先看 FPGA 状态和服务
cat /sys/class/fpga_manager/fpga0/state      # operating
tail -5 /var/log/ip2demo.log                 # 应有 PL VERSION = 0x00010000
# 2) 确认板上是"新版位流"（0x40 索引寄存器可写可读回）
python3 /tmp/which_bit.py                    # 应打印【新版】位流
# 3) 用已知尺寸靶图验证检出范围（3/6/10/20/30 px）
python3 /tmp/probe64.py
# 4) 浏览器打开实时预览
#    http://169.254.67.100:8080/
```

如果 2) 报"旧版位流"，说明自加载没生效，手动执行：

```bash
echo ip2_bd_wrapper.bin > /sys/class/fpga_manager/fpga0/firmware
/etc/init.d/ip2demo restart
```
"""
with io.open(p, "a", encoding="utf-8") as f:
    f.write(sec)
print("appended", len(sec), "chars")
