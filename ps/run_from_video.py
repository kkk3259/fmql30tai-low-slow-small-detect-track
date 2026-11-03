# -*- coding: utf-8 -*-
"""run_from_video.py —— 用视频文件当相机，起完整的 cam3d_pipe 服务（验证新代码）。

不预载全部帧（1280x720x644 帧会吃 1.8GB 内存被 OOM 杀掉），改为按需读 + 读到头回绕。
用法: python3 run_from_video.py /root/user2.mp4 8080
"""
import sys

import cv2

VID = sys.argv[1] if len(sys.argv) > 1 else "/root/user2.mp4"
PORT = sys.argv[2] if len(sys.argv) > 2 else "8080"

_RealCap = cv2.VideoCapture


class FakeCap(object):
    def __init__(self, *a, **kw):
        self.c = _RealCap(VID)
        self.ok = self.c.isOpened()
        self.w = int(self.c.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
        self.h = int(self.c.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
        self.n = 0
        print("[fake-cam] %s %dx%d" % (VID, self.w, self.h), flush=True)

    def isOpened(self):
        return self.ok

    def read(self):
        ok, f = self.c.read()
        if not ok:                       # 回绕，模拟循环推流
            self.c.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, f = self.c.read()
        self.n += 1
        if self.n % 100 == 0:
            print("[fake-cam] %d frames" % self.n, flush=True)
        if ok and f is not None and (f.shape[0] != 480 or f.shape[1] != 640):
            f = cv2.resize(f, (640, 480))
        return ok, f

    def get(self, prop):
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self.w)
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self.h)
        if prop == cv2.CAP_PROP_FPS:
            return 30.0
        return 0.0

    def set(self, prop, val):
        return self.c.set(prop, val)

    def release(self):
        self.c.release()


cv2.VideoCapture = FakeCap

sys.argv = ["cam3d_pipe.py", "--port", PORT, "--npu", "1", "--mode", "roi",
            "--quality", "75", "--push-every", "1"]
sys.path.insert(0, "/root/ip2")
import cam3d_pipe  # noqa: E402
cam3d_pipe.find_cam = lambda *a, **kw: 0   # 骗过 USB 相机检测

print("[fake-cam] starting service on :%s" % PORT, flush=True)
cam3d_pipe.main()
