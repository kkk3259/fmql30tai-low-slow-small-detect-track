# FMQL30TAI 低小慢目标检测 · 模型与部署文件

> YOLOv11n 单类（drone）无人机检测模型，训练于 DUT Anti-UAV Detection 数据集，
> 已完成 Icraft INT8 量化并生成 FMQL30TAI（ZhuGe NPU）上板文件。
> 生成日期：2026-10-19。工具链：ultralytics 8.3.163 / torch 2.14.1 / Icraft v3.39.0。

## 目录说明

```
model/
  best.pt                  最优权重（第 98/100 轮，微调或评估用）
  args.yaml                训练完整参数（seed=0，可复现）
  results.csv / results.png 训练全程指标与曲线
  deploy_export.py         best.pt → 截断版 ONNX 的导出脚本（重训后重跑即可）
deploy/
  yolo11n_drone_trunc_ZG.json + .raw   ★上板文件（runtimeapp 直接加载）
  yolo11n_drone_trunc_640_opset17.onnx  截断版 ONNX（重做 Icraft 转换的输入；_ir8 为 IR8 副本）
  yolo11n_drone_int8.toml               Icraft 转配置（校准集 128 张 DUT 图，路径需按本机改）
  cpu_decode_demo.py                    板端 CPU 后处理参考实现（已数值验证）
```

## 模型指标（DUT test 集，独立评估）

| P | R | mAP50 | mAP50-95 |
| --- | --- | --- | --- |
| 0.948 | 0.859 | **0.920** | 0.619 |

按 640 输入目标宽分档的召回率：<8px 48.5% / 8–16px 78.8% / 16–32px 90.5% / ≥32px 95.1%；conf=0.25 误报 84 框/2200 图。
INT8 量化后（宿主机对拍）：框 IoU 均值 0.907，conf 平均差 ~0.11（含预处理方式差异）。

## 使用要点

1. **上板**：`deploy/*_ZG.json + .raw` 交 runtimeapp 加载；模型输入 640×640，**RGB、NHWC、UINT8**（/255 归一化已折入量化，板端不要再做）。
2. **后处理**：模型输出 `box_raw[1,64,8400]`、`cls_raw[1,1,8400]`（截断头，无 DFL/Sigmoid），CPU 侧按 `cpu_decode_demo.py` 移植：DFL→dist2bbox→×stride→sigmoid→NMS。8400 排列：8 倍层 80×80 → 16 倍层 40×40 → 32 倍层 20×20，层内行优先。
3. **重做转换**（换权重后）：Windows 下跑 `model/deploy_export.py` 重导出 → 用 `deploy/yolo11n_drone_int8.toml` 依次 `icraft parse/optimize/quantize/adapt/generate`。**generate 仅 Windows 版 Icraft 支持**（Linux 包缺 zhuge codegen 库）；Icraft 工作路径必须纯 ASCII、无中文。
4. **微调**（接入自采数据后）：以 `model/best.pt` 为起始权重继续训练。

## 已知限制

- 训练域为 DUT 公开数据，与实拍（OV5640 摄像头）存在域差，实机指标需现场再评；
- 识别距离结论（默认 3.34mm 镜头）：10–15m 可靠（召回 90%+），20m 约 79%（0.35m 机型），换 6mm 镜头可提升 20m 档至 90% 级。
