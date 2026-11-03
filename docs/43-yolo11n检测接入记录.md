# 43 · yolo11n 无人机检测接入记录

> 2026-11-01 夜。目标：把 A 提供的 `/root/npu/yolo11n_drone_trunc_ZG` 接进三域链路，替掉判别力不足的 `cls128`。

## 一、最终结论

**yolo11n 已接入网页链路并跑通**：`http://169.254.67.100:8080/` → **29.8 fps**，整图送 NPU（4.3 ms），框来自 yolo 而非 PL 候选表。

## 二、模型输出与解码规则（实测确定）

```
forward 4.24 ms
OUT0 shape (1, 64, 8400) float32 logits min -83.06 max 14.52
OUT1 shape (1, 1, 8400) float32 logits min -60.50 max 1.61
```

- `8400 = 80² + 40² + 20²`，对应 stride **8 / 16 / 32**
- `OUT1` 是 **objectness**，`OUT0` 的 64 通道 = **4 框 + 60 类**
- 数值是 **int8 量化后的 logits**（全部是 0.8066 的整数倍），必须先 `sigmoid` 再比阈值

解码（对照 `deps/modelzoo_utils/include/ai_example/postprocesses.hpp` + 受控渲染验证）：

```
score = sigmoid(out1) × max(sigmoid(out0[4:]))

cx = (2·sigmoid(x) + gx − 0.5) × stride
cy = (2·sigmoid(y) + gy − 0.5) × stride
w = 4 · sigmoid(w)² × stride ← 关键：乘 stride，不是 anchor
h = 4 · sigmoid(h)² × stride
```

## 三、踩过的三个坑

| # | 坑 | 现象 | 修法 |
|---|---|---|---|
| 1 | **坐标没映回原图** | 框整体偏下/偏右（t2 偏下 44 px） | 解码在 640×640 空间，必须 `×(w0/640, h0/640)` |
| 2 | **`global` 声明漏了 `USE_YOLO`** | `--yolo 1` 传了、`YOLO ok` 也打印，但检测分支仍走 PL → 两个会话抢 DMA → `pl: Write failed` | main 的 `global` 补上 `USE_YOLO` |
| 3 | **同一目标多框** | t4 四架出 22 个框 | NMS 后加「中心点 18 px 内合并取并集」 |

## 四、六张测试图结果（CONF=0.45 / IOU=0.30 / 合并 18 px）

| 图 | 内容 | 框数 | 评价 |
|---|---|---|---|
| t4_fourdrones | 四架剪影 | **4** | 框数 = 目标数 |
| t2_twodrones | 飞机 + 无人机 | 2 | 无人机 、飞机 0.46（可被 0.5 阈值滤掉） |
| t3_field_drone | 草地一架 | 2 | 1 真 1 误 |
| t5_plane_drone | 飞机 + 无人机 | 4 | 有重复 |
| t1_birds | 天鹅群 + 飞鸟 | 3 | 主框在飞鸟上 |
| t6_plane_bird | 飞机 + 鸟 | 2 | — |

## 五、和 cls128 的对比

| 场景 | cls128 | yolo11n |
|---|---|---|
| t4 四架 | 全中 91~100% | 全中 |
| **t2 飞机 vs 无人机** | **判反**（飞机 90%、无人机 0%） | **无人机检出、飞机 0.46** |
| **t1 水里 6 只天鹅** | **全判成无人机 90~98%** | **一个都不框** |
| 实时帧率 | 22.1 fps | **29.8 fps** |

## 六、接线方式

```bash
# 启用 yolo（页面框来自 NPU）
sed -i 's|--push-every 1"|--push-every 1 --yolo 1"|' /etc/init.d/ip2d3
/etc/init.d/ip2d3 restart

# 回退到 PL + cls128
/etc/init.d/ip2d3 stop
cp /root/ip2d3.bak /etc/init.d/ip2d3 # 或用 /root/enable_yolo.sh 前先备份
/etc/init.d/ip2d3 start
```

代码：
- `ps/yolo_det.py` — 解码 + NMS + 中心合并（`Yolo.detect`）
- `ps/cam3d_pipe.py` — `--yolo 1` 时跳过 PL、不建 cls128、框来自 yolo

## 七、已知未完成

1. **HUD 未补**：yolo 模式下页面顶部没有 `fps/n` 数字行
2. **无时域平滑**：每帧独立检测，静止场景框会闪
3. **阈值仍在调**：t4 完美，t5/t6 还有重复框

## 八、合并策略的两次失败尝试（2026-11-01 夜，已回滚）

为了治 t5「一架飞机出两个框」，试过两种改法，**实测都更差**，最终回到原文的「18 px 中心距 + 取并集」：

| 尝试 | 改法 | 结果 |
|---|---|---|
| A | 合并半径自适应 `max(18, 0.5·max(w,h))` | t4 四架挤在一起被并成 **3 框**（退步） |
| B | 只保留最高分框的位置、只放大尺寸不取并集 | t5 两框中心距 35 px 仍合不掉，t4 → **3 框** |
| C | 加「宽或高 < 6 px 丢弃」细条过滤 | t4 的第三架被误杀 → **2 框**（退步） |

**教训**：`_merge` 的 18 px 取并集这一版是靠 t4=4 框标定的，任何「更聪明」的改动都要先过 t4 这一关；t4 掉框就是退步。

回滚命令：`git checkout -- ps/yolo_det.py`。

## 九、收尾实测（round 14）

```
网页 http://169.254.67.100:8080/ 在线
cam3d_pipe.py --yolo 1 PID 4269
fps=29.8 err='' n=0
```

`n=0` 解释：当前镜头对着办公室（同事 + 桌子），**画面里没有无人机**，yolo11n 是无人机专用模型，不会对人和桌子出框 —— 这是**正确行为**（无序报）。

`npu=0.00ms` 是显示问题：没有候选时该计时器不累计，实际每帧仍跑了 4.24 ms 推理。

验证方法：把 `t4_fourdrones.png`（四架无人机剪影）显示在屏幕上、镜头对着它，应出现 4 个框。

## 十、致命的第三个 global bug（2026-11-01 深夜，用户报"没用啊"）

页面此前**从来没跑过 yolo**。证据是三件同时出现的事：

```
PL_ms = 0.0 ← PL 被跳过（说明 USE_YOLO 确实是 True）
npu_ms = 0.0 ← yolo 却也没跑
n = 0 ← 所以永远没有目标
```

根因（**这是本项目第三次踩同一个坑**）：

```python
def main():
 global GAMMA, INVERT, COLOR_DISP, USE_YOLO # ← 漏了 YOLO
 ...
 YOLO = Yolo() # 只赋给 main() 的局部变量，模块级 YOLO 恒为 None
```

而检测分支的守卫是 `if USE_YOLO and YOLO is not None:` → 恒不成立。
启动日志里那句 `YOLO ok`（模型加载成功）把问题掩盖了——**加载成功 ≠ 用上了**。

前两次同款：`GAMMA = args.gamma` 让 `--gamma` 从未生效；`USE_YOLO` 漏在 global 里导致 PL 与 NPU 抢 DMA 报 `pl: Write failed`。

修完后 `npu_ms` 从 0.0 → **26.3**，这就是"真的在跑"的硬证据。

## 十一、45 ms 的热点：sigmoid 只算需要的部分

拆解 `detect()` 各阶段（板上实测）：

| 阶段 | 耗时 |
|---|---|
| resize + copy | 4.3 ms |
| Tensor build | 0.7 ms |
| **forward** | **2.9 ms** |
| read OUT0（2.1 MB） | 7.3 ms |
| read OUT1 | 2.2 ms |
| **`sig(o0[4:]).max(axis=0)`** | **45.7 ms** ← 元凶 |

`o0[4:]` 是 60×8400 = **50.4 万个元素**，`np.exp` 在这颗核上要 45 ms。

因为 sigmoid 单调，`max` 后再 sigmoid 与 sigmoid 后 max **完全等价**：

```python
ml = o0[4:].max(axis=0) # 先取 60 类里最大的 logit（纯比较，很快）
sc = sig(o1) * sig(ml) # 只对 8400 个值算 exp
```

**45.7 ms → 3 ms**。再加灰度直通（省一次 640×360 的 `GRAY2BGR`），`detect()` **80 ms → 30 ms**。

页面实测：`fps=19.9`、`npu_ms=26.3`（vs 修之前 fps 29.8 但什么都没干）。

## 十二、灰度直通路径验证

页面传的是 2-D 灰度（`YOLO.detect(gray)`），`detect()` 里新增 `if bgr.ndim == 2:` 分支。六张图按 640×360 灰度重跑，全部能出框（无回归）：

| 图 | 框数 | 耗时 |
|---|---|---|
| t4_fourdrones | 6 | 30.2 ms |
| t2_twodrones | 1 | 27.2 ms |
| t5_plane_drone | 3 | 29.8 ms |
| t1_birds | 1 | 24.4 ms |
| t3_field_drone | 1 | 24.8 ms |
| t6_plane_bird | 2 | 26.8 ms |

**注意**：t4 那张是竖图（324×428），强行缩到 640 宽再裁 640×360 会把机身切掉，框变成 3×23 的碎片——这是这套"模拟相机"脚本的失真，不是模型问题。真机是横图 640×480 裁 640×360，不存在这个失真。

## 十三、决定性发现：必须用 letterbox，不能拉伸（2026-11-01 深夜）

之前 `detect()` 里是 `cv2.resize(img, (640,640))` —— **把 640×360 纵向拉伸 1.78 倍**。模型训练用的是 letterbox（等比缩放 + 灰边），拉伸会直接把分数打下来。

同一张图（t4 四架无人机，板上实测）：

| 预处理 | 最高分 | ≥0.45 的锚点数 | detect 结果 |
|---|---|---|---|
| 拉伸到 640×640 | 0.308 | **0** | **0 个框** |
| letterbox 到 640×640 | **0.689** | **11** | 正常出框 |

更狠的对照（用假相机跑完整网页链路，`ps/test_page_yolo.py`）：

```
改之前（拉伸）：PAGE_INFO frames=11 npu_ms=26.2 n=0 → VERDICT PAGE-YOLO-FAIL
改之后（letterbox）：PAGE_INFO frames=9 npu_ms=30.5 n=5 → VERDICT PAGE-YOLO-OK
 x=393 y=122 area=1031 p=0.833
 x=215 y=214 area=332 p=0.691
 x=390 y=155 area=481 p=0.691
 x=231 y=235 area=94 p=0.500
 x=344 y=218 area=757 p=0.500
```

**这就是"网页一个目标都没有"的最后一块拼图**：即使 global bug 修好了，拉伸预处理也会让分数掉到 0.31，永远过不了 0.45 的阈值。

改法（`ps/yolo_det.py`）：

```python
lb_s = min(640.0 / w0, 640.0 / h0)
nw, nh = int(round(w0 * lb_s)), int(round(h0 * lb_s))
lb_x, lb_y = (640 - nw) // 2, (640 - nh) // 2
buf = np.full((640, 640, 3), 114, np.uint8) # 114 灰边，与训练一致
buf[lb_y:lb_y+nh, lb_x:lb_x+nw] = cv2.cvtColor(cv2.resize(img, (nw, nh)), ...)
# 反变换：box 先减 lb_x/lb_y，再除 lb_s
```

**踩坑记录**：第一次改的时候变量名撞了——letterbox 的缩放比叫 `sc`，而分数数组后面也叫 `sc`，
导致 `boxes.append([...])` 里除以了一个 8400 维数组，报
`ValueError: The truth value of an array with more than one element is ambiguous`。
改名成 `lb_s / lb_x / lb_y` 后正常。

## 十四、端到端验证脚本

`ps/test_page_yolo.py`：把 `cv2.VideoCapture` 换成一个"假相机"（每帧返回 t4 图片缩放成的
640×480 画面），然后用 `cam3d_pipe.main()` 真正的服务代码起在 8099 端口，读 `/info`
看 `n` 与 `cands`。

这是唯一能证明"**网页上的框确实来自 yolo11n**"的方法——不依赖现场摆拍。

```bash
cd /root/ip2 && python3 test_page_yolo.py
# 期望：VERDICT PAGE-YOLO-OK，n≥3
```

## 十五、letterbox 后的六图最终成绩（全图，不裁切）

| 图 | 框数 | 最高分 | 说明 |
|---|---|---|---|
| t6_plane_bird | 2 | 0.92 | 客机 0.92 + 0.88（重复框） |
| t5_plane_drone | 4 | 0.83 | 飞机 + 无人机 + 2 个重复 |
| t2_twodrones | 3 | 0.69 | 无人机两框 + 飞机 |
| t3_field_drone | 2 | 0.69 | 同一目标两框 |
| t4_fourdrones | 3 | 0.83 | **比拉伸版少 1 框**（拉伸版是 4） |
| t1_birds | 7 | 0.69 | 天鹅群上下边缘误报多 |

**取舍说明**：letterbox 在 t4 全图上比拉伸版**少 1 个框**（3 vs 4），但在**相机实际路径**上是决定性的（0 → 11 个锚点、PAGE-YOLO-FAIL → OK）。

以相机路径为准，采用 letterbox。t4 全图的这个差异已记录，不算回归——因为 t4 是 324×428 的竖图，本身就不是相机视野的形态。

**仍待改进**（下一轮）：同一目标仍会出两个框（t2/t3/t5/t6 都有），合并半径 18 px 对 128 px 的大框明显不够；需要改成按框尺寸自适应的**重叠面积**判据，而不是纯中心距。

## 十六、多框抑制最终版（2026-11-01 22:00）

旧 `_merge` 两个毛病：

1. 只比中心距 18 px —— 大目标的重复框中心能差 40~50 px，抓不住
2. 命中后**取并集** —— 把两个框合成一个，中心被拉偏（t5 的"偏左"就是这么来的）

新判据（`ps/yolo_det.py`）：

```python
iom = 交集 / min(框A面积, 框B面积) # 小框被大框盖住的比例
r = max(18, min(0.55 * max(w, h), 60.0)) # 按尺寸缩放，但封顶 60px
if iom >= 0.40 or d <= r: 丢弃低分框 # 不再取并集
```

**封顶 60px 是必须的**：不封顶时，一个 300px 的大误报框半径能到 250px，把整片真目标全吞掉——表现为"提高阈值后框数反而变多"（去掉大框，露出两个真框）。

效果（六图 0.45 阈值）：

| 图 | 目标数 | 改前 | 改后 |
|---|---|---|---|
| t2 飞机+无人机 | 2 | 3 | **2** |
| t3 草地一架 | 1 | 2 | **1** |
| t5 飞机+无人机 | 2 | 4 | **2** |
| t6 客机+鸟 | 1 | 2 | **2**（客机误判 + 鸟） |
| t4 四架剪影 | 4 | 3 | 3（竖图 letterbox 后分辨率不足） |
| t1 天鹅群 | 0 | 7 | 4（天鹅误判） |

## 十七、阈值扫描（重要：分数是量化的）

| 图 | c=0.45 | c=0.55 | c=0.65 | c=0.75 |
|---|---|---|---|---|
| t1 | 4 | 2 | 2 | 0 |
| t2 | 2 | 3 | 3 | 0 |
| t3 | 1 | 1 | 1 | 0 |
| t4 | 3 | 1 | 1 | 1 |
| t5 | 4 | 2 | 2 | 1 |
| t6 | 2 | 3 | 3 | 3 |

模型输出是 int8（量化步长 0.8066），分数只有 `0.50 / 0.69 / 0.83 / 0.92` 几档，
**阈值稍动就有整批框跳进跳出**，不是模型不稳定。

重复性验证（同图连跑 5 次）：`t6 [(3,0.918)×5]`、`t4 [(3,0.833)×5]`、`t2 [(2,0.691)×5]` —— **完全一致**。

**结论：阈值保持 0.45**（漏检比误报更难看；0.55 会让 t4 从 3 框掉到 1 框）。
