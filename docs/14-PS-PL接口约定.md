# 14 · PS ↔ PL 接口约定（草案 v0.1）

> 维护：P（PL）｜ 对接：S（PS/应用）
> 依据：S 2026-10-23 实测的 U-DMA-BUF 参数（帧缓冲区实测确认）
> 状态：**待 S 确认**，确认后 PL 侧按此实现 AXI Master，PS 侧按此实现收发。

---

## 1. 帧缓冲区（板载 U-DMA-BUF，实测确认）

| 项 | 值 |
|---|---|
| 设备节点 | `/dev/udmabuf0`（char 242:0） |
| 物理基址 | **`0x30100000`** |
| 总容量 | 128 MiB（134,217,728 B） |
| 驱动 | ikwzm u-dma-buf 3.2.5 |
| sysfs | `/sys/class/u-dma-buf/udmabuf0/` |
| `sync_mode` | 1（可按 offset/size 局部同步） |
| `dma_coherent` | **0（非缓存一致，必须手动 sync）** |
| 一帧大小 | **230,400 B**（640×360 灰度，8 bit/像素） |
| 第 k 帧地址 | `0x30100000 + k × 230400` |
| 内存归属 | `/proc/iomem` 的 `2fded000-3fffffff` reserved 区（官方给 PL/DMA 留的 258 MB） |

### 1.1 128 MiB 分区

| 区间 | 大小 | 用途 |
|---|---|---|
| `0x30100000` ~ `0x30FFFFFF` | 16 MiB | **输入帧区**（PS 写 / PL 读），72 帧 |
| `0x31000000` ~ `0x310FFFFF` | 1 MiB | **输出区**（PL 写 / PS 读） |
| `0x31100000` ~ `0x380FFFFF` | 111 MiB | 备用（多缓冲 / 中间结果） |

---

## 2. 输出区布局（PL 写）

| 偏移 | 长度 | 内容 |
|---|---|---|
| `0x31000000` + 0 | 36 B | **候选表**（见 §2.1） |
| `0x31000040` + 0 | 4 B | **状态字**（见 §2.2） |
| `0x31000044` + 0 | 4 B | **邮箱请求字**（PS 写 / PL 读，见 §3） |

候选表与状态字放在同一 sync 区间（`sync_offset=0`、`sync_size=44`），PS 一次 sync 全看到。

### 2.1 候选表格式（36 B，PL → PS）

```
byte 0        : n_cand     候选个数（0 ~ 5）
byte 1  ~ 7   : 候选 0      x_hi, x_lo, y_hi, y_lo, 0, area, peak
byte 8  ~ 14  : 候选 1      （同上，7 字节/候选）
byte 15 ~ 21  : 候选 2
byte 22 ~ 28  : 候选 3
byte 29 ~ 35  : 候选 4
```

- `x`、`y`：16 bit 大端（`x_hi` 在前），**左上角坐标，单位为 640×360 降采样后的像素**
- `byte 4`：预留恒 0（原 area 高字节位置）
- `area`：8 bit 连通域面积（像素数），范围过滤 `[2, 200]`
- `peak`：8 bit 连通域内增强图最大值
- 候选按 `peak` **降序**排列，最多 5 个；不足则 `n_cand` 之后填 0

### 2.2 状态字（4 B，PL → PS）

| bit | 含义 |
|---|---|
| 31 | `done`：本帧处理完成（PL 置 1） |
| 30 | `error`：AXI 读超时/异常（PL 置 1） |
| 29:16 | 保留（0） |
| 15:0 | `frame_id`：本次处理的帧号（与邮箱请求字一致，取低 16 位） |

PL 在开始处理新帧时把 `done` 清 0，处理完置 1 → PS 用 `done` 上升沿判断可取结果。

---

## 3. 邮箱协议（PS → PL 触发）

PL 不做连续自由运行，而是**按帧触发**，避免与 PS 写下一帧冲突：

1. PS 把第 k 帧写入 `0x30100000 + k×230400`；
2. PS 按 §4 做 `sync_for_device`（**必须**，`dma_coherent=0`）；
3. PS 把请求字写到 **`0x31000044`**：`frame_id = k`（低 16 位，bit31 恒 0）；
4. PL 轮询 `0x31000044`，发现请求字变化 → 读帧 → 计算 → 写候选表 + 状态字；
5. PS 轮询状态字 `bit31=1` → 做 `sync_for_cpu` → 读 36 B 候选表。

**请求字变化判据**：PL 内部保存 `last_req`，当前值 `!= last_req` 即认为有新帧。PS 因此**不要把帧号写成上一次的值**（否则 PL 不触发）；若需重复处理同一帧，写 `frame_id + 0x10000`（bit16 翻转）即可。

> 备选（若 S 更希望"连续流水"）：PS 只更新一个 `write_ptr`，PL 自增 `read_ptr` 追赶。缺点是要处理覆盖/丢帧。**默认用上面的按帧触发。**

---

## 4. 缓存一致性流程（`dma_coherent=0`，必须做）

**PS 写帧之后、写邮箱之前：**

```sh
echo $((k*230400)) > /sys/class/u-dma-buf/udmabuf0/sync_offset
echo 230400        > /sys/class/u-dma-buf/udmabuf0/sync_size
echo 1             > /sys/class/u-dma-buf/udmabuf0/sync_for_device
```

**PS 读结果之前：**

```sh
echo 0    > /sys/class/u-dma-buf/udmabuf0/sync_offset   # 输出区起点 = 0x31000000
echo 44   > /sys/class/u-dma-buf/udmabuf0/sync_size
echo 1    > /sys/class/u-dma-buf/udmabuf0/sync_for_cpu
```

⚠️ 不 sync 的现象是"随机帧结果错"，极难定位（看起来像逻辑 bug）。
⚠️ `CONFIG_STRICT_DEVMEM` 开着 → `/dev/mem` 访问 `0x30100000` 会被拒绝（`Operation not permitted`），不要试图用 `/dev/mem` 验证地址，只能走完整闭环。

---

## 5. 时序与性能预算

| 项 | 值 | 说明 |
|---|---|---|
| PL 主时钟 | **100 MHz** | 板载 200 MHz 差分（C8/C7）÷2；GP/HP 上限也是 100 MHz |
| AXI 读带宽（64 bit @100 MHz） | 800 MB/s | 一帧 230,400 B ≈ **288 µs** |
| 计算 | ≈ **4.9 ms/帧** | IP2 约 0.49 M 拍（CFAR 虚拟光栅 261,300 + CCL 230,400） |
| 端到端（含 AXI） | ≈ **5.2 ms/帧** | 相对 PS 现在 57.87 ms 的 detect ≈ **11×** |
| PS 侧建议 | 双缓冲/环形 | PL 处理期间 PS 写第 k+1 帧 |

---

## 6. PL 侧实现计划

| 文件 | 作用 | 状态 |
|---|---|---|
| `pl/rtl/ip2_axi_master_rd.v` | AXI4 读主机：按帧地址读 230,400 B，输出 8 bit 流 + valid/ready | 待写 |
| `pl/rtl/ip2_axi_master_wr.v` | AXI4 写主机：写 36 B 候选表 + 4 B 状态字 | 待写 |
| `pl/rtl/ip2_axi_top.v` | 顶层：邮箱轮询 + 读帧 → IP2 流式链 → 收 36 B → 写回 + LED | 待写 |
| `pl/tb/tb_axi_top.v` | 带行为级 AXI 从机（内存模型）的仿真 | 待写 |

**第一版位流策略（分两步，降低风险）**

1. **先出 `ip2_board_top`（图案自测，无 AXI）**：验证 PL 能在板上跑起来 + LED 显示候选数（正常 = 4）。不依赖 PS 侧任何代码。
2. **再出 `ip2_axi_top`（真数据）**：等第 1 步通过 + 本文件被 S 确认后开工，避免两边协议猜错。

---

## 7. 待 S 确认的 5 个点

1. **邮箱位置**：`0x31000044` 是否可用？（若与 PS 侧已有布局冲突，S 指定即可）
2. **触发方式**：按帧触发（§3）是否 OK？还是要连续流水？
3. **图像内容**：输入帧是**原始 720P 降采样后的 640×360 灰度**，还是 PS 已做过 Top-Hat/归一化？PL 侧默认输入就是灰度原图（PL 内部做 5×5 Top-Hat → 31×31 CFAR → CCL）。
4. **同步责任**：`sync_for_device` / `sync_for_cpu` 全部由 PS 侧负责，PL 不涉及 cache —— 确认无异议。
5. **候选表字段**：`x,y` 是**左上角**还是**质心**？PL 现在输出的是**质心**（`cx = (Σx + area/2) / area`）。

---

## 8. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-10-23 | v0.1 | 首版：依据 S 实测的 udmabuf 参数 + PL 侧 AXI Master 方案起草 |
