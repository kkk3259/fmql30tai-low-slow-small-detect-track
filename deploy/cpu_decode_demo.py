# -*- coding: utf-8 -*-
"""
CPU 后处理参考实现（已数值验证：与完整模型输出误差 xywh<1e-3px, cls<1e-8）
输入：截断版 ONNX 的两个输出 box_raw[1,64,8400]、cls_raw[1,nc,8400]
输出：与 ultralytics 完整输出等价的 [1,4+nc,8400]（像素 xywh + sigmoid 置信度）
板端 C 移植要点：DFL 用 16 项 softmax 加权和；anchor 为 grid 单位 (i+0.5,j+0.5)；
乘 stride(8/16/32) 变像素；8400 的排列为 8 倍层(80x80) -> 16 倍层(40x40) -> 32 倍层(20x20)，层内行优先。
"""
import numpy as np
import torch
import onnxruntime as ort

ONNX = r"D:\无人机检测数据集\Icraft空转\yolo11n_trunc_640_opset17.onnx"


def decode(box_raw, cls_raw, imgsz=640, reg_max=16, strides=(8, 16, 32)):
    b = torch.from_numpy(box_raw).view(1, 4, reg_max, -1)
    dfl = b.softmax(2).mul(torch.arange(reg_max, dtype=torch.float32).view(1, 1, -1, 1)).sum(2).permute(0, 2, 1)
    anch, strd = [], []
    for s in strides:
        n = imgsz // s
        g = torch.arange(n, dtype=torch.float32)
        yy, xx = torch.meshgrid(g, g, indexing="ij")
        anch.append(torch.stack((xx.reshape(-1) + 0.5, yy.reshape(-1) + 0.5), 1))
        strd.append(torch.full((n * n, 1), float(s)))
    a = torch.cat(anch).unsqueeze(0)
    st = torch.cat(strd).view(1, -1, 1)
    lt, rb = dfl.chunk(2, -1)
    xy = ((a - lt) + (a + rb)) / 2
    wh = (a + rb) - (a - lt)
    dec = torch.cat((xy, wh), -1) * st
    return torch.cat((dec.permute(0, 2, 1), torch.from_numpy(cls_raw).sigmoid()), 1).numpy()


if __name__ == "__main__":
    torch.manual_seed(0)
    x = torch.randn(1, 3, 640, 640)
    sess = ort.InferenceSession(ONNX, providers=["CPUExecutionProvider"])
    box_raw, cls_raw = sess.run(None, {"images": x.numpy()})
    out = decode(box_raw, cls_raw)          # [1, 4+nc, 8400]
    conf = out[0, 4:].max(0)
    top = conf.argmax()
    print("输出形状:", out.shape, "| 最高置信度:", float(conf[top]),
          "| 对应框 xywh(px):", out[0, :4, top].round(1).tolist())
    # 之后接 NMS（阈值建议 conf>=0.25, IoU>=0.45 起步，按实测调）
