# model/ —— 模型训练与导出

| 文件 | 内容 |
|---|---|
| `best.pt` | YOLOv11n 单类（drone）训练权重 |
| `args.yaml` | 训练超参记录 |
| `results.csv` / `results.png` | 训练过程曲线（loss / mAP）|
| `deploy_export.py` | 导出脚本：`.pt` → ONNX → Icraft 量化 → `.raw` |

## 训练结果

- 模型：YOLOv11n 单类（drone）
- DUT test：**mAP50 = 0.920**，Recall = 0.859
- 量化后精度损失见 `docs/` 中的量化章节

## 导出链条

```
best.pt  --(deploy_export.py)-->  ONNX (opset17)
         --(Icraft 3.39)-->       量化 + 编译
         --(输出)-->              deploy/<name>/<name>_ZG.raw + .json
```

量化标定集在 `deploy/calib/`（129 张）。
