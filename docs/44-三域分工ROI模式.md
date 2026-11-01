# 44 · 三域分工：PL 粗筛 + NPU ROI 精判

> 2026-11-02 凌晨。本文件记录 `--mode roi` 的实现、端到端验证与六图对照结果，
> 包含一个**必须如实写进报告的限制**。

## 1. 架构（为什么这样分工）

文献共识（[边缘侧低慢小无人机检测](https://www.cqvip.com/authorservice/00029HCIMND88JPW6HC04J0P9Y?type=5)、
[Quantized YOLOv8 on Zynq UltraScale+](https://github.com/beatwad/drone-detect)、
[edge UAV detection survey](https://ieeexplore.ieee.org/ielx8/6287639/11323511/11713432.pdf)）：
**粗筛在前端（全分辨率、确定延迟），精判在后端（小窗口、高放大倍率、语义）**。

量化依据：1280×720 画面里 20 px 的无人机，整帧缩到 640×640 后只剩 **10 px**，
而 YOLOv8 的有效感受野是 32~320 px ⇒ 整帧推理对真机必然失效。
裁 96×96 放大到 160 格 ⇒ 放大 **1.67 倍**；若只取 32×32 区域放大到 160 ⇒ 5 倍。

## 2. 实现

### `ps/yolo_det.py: detect_mosaic(crops, grid=2, conf=None, iou=None)`
把 N 块裁片按 grid×grid 拼进 640×640 画布（cell=640//grid，等比缩放居中、114 灰底），
复用 `detect()`；画布本身 640×640 ⇒ letterbox 退化为恒等。
返回 `[(slot, x1, y1, x2, y2, score)]`，坐标已回映到裁片坐标系。

板上实测（`ps/mosaic_test.py`，t4 四架手工裁 4 块 96×96）：
```
grid=4  n=4  43.5 ms   slot0 83% slot1 83% slot2 69% slot3 66%   ← 四架全中
grid=2  n=8  53.3 ms
```

### `ps/cam3d_pipe.py --mode roi`
```
PL 跑 Top-Hat/CFAR/CCL → 候选
  → 每候选裁 96×96（ROI_SIDE=96）
  → 4×4 拼成 640×640（ROI_CELL=4，每格 160×160）
  → yolo11n 一次 forward 判 16 个槽位
  → 每 slot 取最高分，映射回整帧
  → 融合：NPU 认出的用 NPU 的框和分数；没认出的按 ROI_KEEP_PL 决定是否保留（p=0）
```

## 3. 关键 bug：PL 与 NPU 抢 DMA

第一次运行报：
```
pl: Write failed at AXIZG330AIUdmaMemRegionNode::write
```
根因：`PL3D` 与 `Yolo()` 各自 `Device.Open`，icraft 重注册 DMA 区域后接管了 PL3D 的 write。

**修法**：`Yolo.__init__(self, dev=None)` 复用调用方的 Device ——
```python
self.dev = dev if dev is not None else xrt.Device.Open("axi://zg330aiu?npu=0x40000000&dma=0x80000000")
```
`cam3d_pipe` 里改成 `YOLO = Yolo(dev=pl.dev)`。修后 `err=''`。

## 4. 端到端验证（假相机）

`ps/test_page_roi.py`：把 t4 缩到 **45%**（无人机变 15~35 px，接近真实远距离目标）
贴进 640×480，用 `cam3d_pipe.main()` 起真服务在 8099，另一个进程轮询 `/info`。

**注意**：轮询必须用独立进程（`ps/poll_roi.py`），因为 icraft 的 forward 是 C++ 调用、
不释放 GIL，Python 线程会被饿死 —— 一开始我用线程轮询，一条日志都打不出来。

```
PAGE_INFO fps=15.0  npu_ms=36.0  n=2  err=''
PAGE_CANDS 2
   x=276 y=189 area=414  p=0.499
   x=270 y=174 area=1023 p=0.5
VERDICT PAGE-ROI-OK
```

## 5. 六图对照（`ps/offline_roi.py`）

每张图缩到 640×360 灰度 → PL 出候选 → 裁 96×96 → mosaic → yolo 判：

| 图 | PL 候选 | ROI 判出 | 过阈(≥0.45) | top |
|---|---|---|---|---|
| t1_birds | 8 | 1 | 1 | 0.50 |
| t2_twodrones | 3 | **0** | 0 | 0.00 |
| t3_field_drone | 8 | 2 | 2 | 0.83 |
| t4_fourdrones | 3 | **0** | 0 | 0.00 |
| t5_plane_drone | 6 | 5 | 5 | 0.69 |
| t6_plane_bird | 8 | 1 | 1 | 0.50 |

## 6. 必须如实记录的限制

**t2 与 t4 在 ROI 模式下是 0 框，而它们恰恰是整帧 yolo 最好的两张。**

原因不是 NPU，而是**粗筛这一关**：这两张图是近距离特写，无人机 40~120 px，
**超出 PL 的 6~28 px 检测窗口**，PL 给出的候选根本不是无人机，ROI 自然判不出。

结论：
- **ROI 模式适用于小目标**（远距离无人机，2~30 px）——这正是比赛场景，也是假相机 45% 缩放能跑通的原因
- **整帧 yolo 适用于大目标**（近距离特写）
- 两者不是替代关系。真正该做的是**按目标尺度自适应**：PL 报出候选的 area 落在窗口内才走 ROI，
  窗口外的走整帧推理 —— 这一步还没做。

## 7. 复现命令

```bash
# 端到端（假相机，端口 8099）
pkill -9 -f cam3d_pipe; sleep 3
cd /root/ip2 && NOPOLL=1 setsid nohup python3 test_page_roi.py > /root/roi2.log 2>&1 < /dev/null &
sleep 20 && python3 poll_roi.py 8099

# 六图对照
bash /root/run_roi6.sh

# 网页（默认整帧 yolo，稳定 20fps）
/etc/init.d/ip2d3 start
```
