# deploy/ —— 部署模型与标定数据

本目录存放 INT8 量化后可直接下发到 ZG330 NPU 的模型（`.raw` 格式）、对应的网络描述（`.json`）、
量化标定集与评测样本。**推理时只需 `.raw` + `.json` 两个文件**，其余是训练/验证阶段的配套数据。

---

## 一、模型清单（按用途）

| 目录 / 文件 | 输入尺寸 | 用途 | 体积 |
|---|---|---|---|
| **`cls128/`** | 128×128 | **二分类（无人机 / 非）—— 主用** | 1.7 MB |
| `grid16/` / `grid64/` | 16×16 / 64×64 | 网格化粗筛变体 | 1.9 MB each |
| `tiny256/` | 256×256 | 小输入检测变体 | 4.9 MB |
| `yolo11n_drone_trunc_ZG.raw` | 640×640 | YOLOv11n 单类检测（主模型） | 4.8 MB |
| `yolo11n_drone_trunc_640_opset17.onnx` | 640×640 | 上者对应的 ONNX（FP32，供转换与对照） | 10 MB |
| `yolo11n_drone_trunc_640_opset17_ir8.onnx` | 640×640 | INT8 量化中间态 | 10 MB |

每个模型目录下是一个三元组：

```
<name>_ZG.raw    量化后的权重（下发到 NPU）
<name>_ZG.json   网络结构描述（算子列表、张量形状）
<name>_ZG.toml   量化配置（或 *_int8.toml）
```

---

## 二、配套数据

| 目录 | 内容 |
|---|---|
| `calib/` | INT8 量化标定集（129 张）|
| `cls128/`、`grid*/`、`tiny256/` 下的图片 | 各自模型的验证样本 |
| `eval_roi_448/` | 448×448 裁剪的 ROI 评测集（201 张，用于级联判别命中率评估）|
| `names/` | 类别名映射 |

> 评测命中率的正确用法：用 test 集独立抽样（不是训练用过的标定图），否则命中率会虚高。
> 详见 `docs/` 中的级联验证章节。

---

## 三、怎么用

### 板上推理（Python）

```python
import icraft.xrt as xrt
import icraft.xir as xir
from icraft.zg330backend import ZG330Backend    # 注意不在 xrt 里
from icraft.host_backend import HostBackend

net = xir.Network.CreateFromJsonFile("<name>_ZG.json")
net.lazyLoadParamsFromFile("<name>_ZG.raw")     # .raw 权重

dev  = xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
sess = xrt.Session.Create([ZG330Backend, HostBackend], net.view(0),
                          [dev, xrt.HostDevice.Default()])
sess.apply()                                    # 必须先 apply

t = xrt.Tensor(...)                             # NHWC、uint8、形状见上表
outs = sess.forward([t])
buf = bytearray(8)
outs[0].read(buf, 0, 8)                         # 唯一可用的回读方式
```

配套脚本见 `ps/cascade.py`（PL 候选 → 裁剪 → 判别）。

### 转换流程

```
PyTorch .pt  →  ONNX (opset17)  →  Icraft 量化  →  .raw + .json
```

转换用 Icraft 3.39（板上库为 3.33.1，主版本一致即可，会打一条 warning）。

---

## 四、踩过的坑

| 现象 | 真因 | 解决 |
|---|---|---|
| `MMU isn't enabled, Please enable MMU first!` | 板上烧的是**不含 AI_Mate 的位流**，ZG330 后端初始化失败，错误被吞成这一句 | 换成三域位流，不是怀疑 Python 版本 |
| `Tensor.dump()` 报 InternalError | 该 API 在 Python 绑定里不可用 | 用 `outs[i].read(buf, 0, n)` |
| 第二次 `Device.Open` 段错误 | 同进程重复打开设备 | 共享同一个 `dev` 对象 |
| 非正方形输入（352×640） | 工具链限制，`.raw` 从 5 MB 膨胀到 30~47 MB | 只用 640×640 |
| 输入报 `IndexError: _Map_base::at` | 布局写成了 NCHW | 必须 NHWC `[1,H,W,3]`、uint8 |
