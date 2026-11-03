# 33 · NPU 级联实测记录（2026-10-31 夜）

> 本文只记录**板上实测**的数字，没测过的不写。
> 板卡 FMQL30TAI676HM（悟净 Lite），三域位流 `ours3d_s2.bin`（PS7 + AI_Mate + 我们的检测器）。

## 1. 结论摘要

| 能力 | 状态 | 实测数字 |
|---|---|---|
| NPU 设备打开 | | `device: 25122301`、`npu: 0x40000000`、`dma: 0x80000000` |
| 模型加载（json+raw） | | cls128 `ops = 121`、yolov5s `ops = 114` |
| `apply()` | | cls128 704.8 ms、yolov5s 452.4 ms（一次性的算子下发） |
| 前向推理 | | cls128 **0.68 ms**、yolov5s **2.7 ms** |
| 输出回读 | | `outs[0].read(bytearray, 0, n)` 拿到 2×float32 |
| PL→NPU 级联 | | 8 个候选逐个判，总 **7.2 ms（0.90 ms/个）** |

## 2. 可复现的调用序列

```python
import icraft.xrt as xrt
import icraft.xir as xir
from icraft.zg330backend import ZG330Backend # 注意：不在 xrt 里
from icraft.host_backend import HostBackend

net = xir.Network.CreateFromJsonFile(JSON_PATH)
net.lazyLoadParamsFromFile(RAW_PATH) # .raw 权重

dev = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
sess = xrt.Session.Create([ZG330Backend, HostBackend], net.view(0),
 [dev, xrt.HostDevice.Default()])
sess.apply()

buf = bytearray(8)
outs = sess.forward([t_in]) # t_in 见下
outs[0].read(buf, 0, 8) # 两个 float32
```

### 输入要求（踩过的坑）

| 项 | 要求 |
|---|---|
| 布局 | **NHWC** `[1, H, W, 3]`，写 NCHW 会报 `IndexError: _Map_base::at` |
| dtype | `uint8`（0~255） |
| 尺寸 | cls128 → `[1,128,128,3]`；yolov5s → `[1,352,640,3]` |
| 顺序 | 必须先 `sess.apply()`，否则报 `Session must be applied before forward` |

### 输出回读（六条错路 + 一条对路）

| 尝试 | 结果 |
|---|---|
| `np.array(outs[0])` | 进程崩 `icraft::InternalError` |
| `outs[0].dump(f, "f32")` | `InternalError`（fmt 语义未知） |
| `outs[0].copyData(chunk)` | 签名只收 buffer → TypeError |
| `outs[0].to(host_region)` | `InternalError` |
| `host.copyFrom(0, out, 0, 8)` | 不报错但值恒 0 |
| `sess.forward([in],[out])` 双参 | `InternalError` |
| **`outs[0].read(buf, 0, n)`** | 正确 |

> **重要教训**：上面那一堆 `InternalError` 我一度归因于“Python 绑定 3.39 与库 3.33 ABI 不一致”，**这是错的**。
> 真因是当时板上烧的是**独立检测器位流**（没有 AI_Mate），`ZG330BackendNode::init` 失败，
> 错误被吞成 `MMU isn't enabled, Please enable MMU first!`，于是所有 Tensor 操作都炸。
> 换三域位流后**一次通过**。
> 所以：看到 `MMU isn't enabled` 先查位流里有没有 AI_Mate，不要怀疑 Python 版本。

## 3. 级联脚本 `ps/cascade.py`

```
Classifer. predict(img128_bgr) -> (p0, p1)
 crop_box(gray, x, y, side, out=128) 按目标边长裁正方形再缩放
--boxes 手工框
--from-pl 走 detect3d.Det3D 拿 PL 候选
--side/--zoom/--thr/--cls/--limit
```

实测（三域位流，`card_synth.png`）：

```
PL: VERSION=0x00010000 base=0x1000 status=0x00000804 n=8 31.2 ms
NPU: 8 个候选逐个判，总 7.2 ms（0.90 ms/个）
 全部 [0.999, 0.000]（判为非无人机）
```

分类器判别力抽查（cls128 二分类模型）：

| 输入 | 输出 [p0, p1] | 说明 |
|---|---|---|
| 纯噪声 | [0.999, 0.000] | 明确否定 |
| 天空+暗点（`bird.mp4` 第 300 帧） | [0.692, 0.299] | **有反应** |
| 天空+亮点 | [0.999, 0.000] | 否定 |
| 靶图白方块 | [0.999, 0.000] | 否定 |
| 合成无人机剪影（真值坐标裁） | [0.236,0.763] / [0.094,0.905] / [0.291,0.708] | **判为无人机** |

⇒ 模型对“无人机形状”确实有判别力，但对“暗点”会给 0.3 的模糊分，属于正常。

## 4. 可用的模型清单（`repo/deploy/`，队友 A 提交 `7b54996`）

| 模型 | 大小 | 输入 | 用途 |
|---|---|---|---|
| `cls128/cls128_drone_ZG.raw` | 1.73 MB | 128×128 | 二分类：无人机/非 |
| `grid16/grid16_drone_ZG.raw` | 1.87 MB | 16×16 网格 | 粗筛 |
| `grid64/grid64_drone_ZG.raw` | 1.87 MB | 64×64 网格 | 粗筛 |
| `yolo11n_drone_trunc_ZG.raw` | 4.79 MB | — | 检测 |
| `tiny256/yolo11n_tiny256_ZG.raw` | 4.88 MB | 256×256 | 检测 |
| `yolov5s_352x640_ZG.raw`（官方示例） | 8.63 MB | 352×640 | 人/车通用 |

## 5. 还没打通的

1. 三域里检测器坐标错乱：`status=0x00000804 err=1`、x 被压缩、两个簇间距恒 320。
 已在适配层 `ip2_user_op.v` 定位并修了 4 个 bug（AR 重置地址 / 字节交织 / 首地址未装载 / 突发末拍地址不推进），
 fix5 编译中，待上板验证。
2. **`err=1`**：检测器写完候选表后等 DDR 写完成，而写通道我们没接（`cand_bytes=0` 走寄存器窗口）。
 属"无害但会提前掐帧"，修法是让 FSM 忽略写完成或把写通道接上。
