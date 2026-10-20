# -*- coding: utf-8 -*-
"""部署导出：best.pt -> 截断版 ONNX（剪掉 DFL/Sigmoid/Concat）+ onnxslim + IR8 + 数值校验
产物输出到 D:/icraft_work/（Icraft 要求纯 ASCII 路径）"""
import os
import subprocess
import sys
import types

import numpy as np
import torch

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
OUT = r"D:\icraft_work"
BEST = os.path.join(REPO, "runs", "detect", "dut_drone_yolo11n_6402", "weights", "best.pt")
NAME = "yolo11n_drone_trunc_640_opset17"
OPSET, IMGSZ = 17, 640

from ultralytics import YOLO  # noqa: E402
import onnx  # noqa: E402
import onnxruntime as ort  # noqa: E402

torch.manual_seed(0)
m = YOLO(BEST)
net = m.model
net.eval()
net.fuse(verbose=False)
head = net.model[-1]
print(f"模型: nc={head.nc}, 输入{IMGSZ}, 参数量见训练报告")


def trunc_forward(self, x):
    for i in range(self.nl):
        x[i] = torch.cat((self.cv2[i](x[i]), self.cv3[i](x[i])), 1)
    shape = x[0].shape
    x_cat = torch.cat([xi.view(shape[0], self.no, -1) for xi in x], 2)
    return x_cat.split((self.reg_max * 4, self.nc), 1)


x = torch.randn(1, 3, IMGSZ, IMGSZ)
with torch.no_grad():
    out = net(x.clone())
    y_full = (out[0] if isinstance(out, tuple) else out).numpy()
    head.forward = types.MethodType(trunc_forward, head)
    box_t, cls_t = net(x.clone())
    head.forward = trunc_forward.__wrapped__ if hasattr(trunc_forward, "__wrapped__") else head.forward

onnx_path = os.path.join(OUT, NAME + ".onnx")
with torch.no_grad():
    head.forward = types.MethodType(trunc_forward, head)
    try:
        torch.onnx.export(net, x, onnx_path, input_names=["images"],
                          output_names=["box_raw", "cls_raw"],
                          opset_version=OPSET, do_constant_folding=True, dynamo=False)
    except TypeError:
        torch.onnx.export(net, x, onnx_path, input_names=["images"],
                          output_names=["box_raw", "cls_raw"],
                          opset_version=OPSET, do_constant_folding=True)
    head.forward = None  # 恢复类方法（删实例属性即可）
    del head.forward

# onnxslim 规范化（CLI 稳定）
subprocess.run([r"D:\anaconda3\envs\pytorch\Scripts\onnxslim.exe", onnx_path, onnx_path + ".slim"],
               check=True, capture_output=True)
os.replace(onnx_path + ".slim", onnx_path)

g = onnx.load(onnx_path)
g.ir_version = 8
onnx.save(g, onnx_path.replace(".onnx", "_ir8.onnx"))
ir = onnx.load(onnx_path)
print(f"ir_version={ir.ir_version}, opset={[(o.domain or 'ai.onnx', o.version) for o in ir.opset_import]}")
print("输出:", [o.name for o in ir.graph.output], "|", [[d.dim_value or d.dim_param for d in o.type.tensor_type.shape.dim] for o in ir.graph.output])

# onnxruntime 数值校验
sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
box_o, cls_o = sess.run(None, {"images": x.numpy()})
md = lambda a, b: float(np.abs(np.asarray(a) - np.asarray(b)).max())
print(f"[1] onnx vs torch截断: box {md(box_o, box_t.numpy()):.2e}, cls {md(cls_o, cls_t.numpy()):.2e}")

# CPU 解码 vs torch 完整输出
b = torch.from_numpy(box_o).view(1, 4, 16, -1)
dfl = b.softmax(2).mul(torch.arange(16.).view(1, 1, 16, 1)).sum(2).permute(0, 2, 1)
anch, strd = [], []
for s in (8, 16, 32):
    n = IMGSZ // s
    gg = torch.arange(n).float()
    yy, xx = torch.meshgrid(gg, gg, indexing="ij")
    anch.append(torch.stack((xx.reshape(-1) + 0.5, yy.reshape(-1) + 0.5), 1))
    strd.append(torch.full((n * n, 1), float(s)))
a = torch.cat(anch).unsqueeze(0)
st = torch.cat(strd).view(1, -1, 1)
lt, rb = dfl.chunk(2, -1)
dec = torch.cat((((a - lt) + (a + rb)) / 2, (a + rb) - (a - lt)), -1) * st
cpu_out = torch.cat((dec.permute(0, 2, 1), torch.from_numpy(cls_o).sigmoid()), 1).numpy()
print(f"[2] 截断+CPU解码 vs torch完整: xywh {md(cpu_out[:, :4], y_full[:, :4]):.2e}, cls {md(cpu_out[:, 4:], y_full[:, 4:]):.2e}")
print("完成:", onnx_path)
