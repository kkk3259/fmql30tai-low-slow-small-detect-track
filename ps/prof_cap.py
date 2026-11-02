# -*- coding: utf-8 -*-
import time

import cv2

c = cv2.VideoCapture(0)
c.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
c.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
for _ in range(5):
    c.read()
t = time.time()
for _ in range(30):
    c.read()
dt = (time.time() - t) / 30
print("cap.read = %.1f ms -> %.1f fps" % (dt * 1000, 1.0 / dt))
# 再加一次编码
ok, f = c.read()
t = time.time()
for _ in range(10):
    cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 70])
dt2 = (time.time() - t) / 10
print("encode(640x480) = %.1f ms" % (dt2 * 1000))
print("采集+编码 串行 = %.1f ms -> %.1f fps" % ((dt + dt2) * 1000, 1.0 / (dt + dt2)))
c.release()
