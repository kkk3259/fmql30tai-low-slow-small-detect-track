import time
import numpy as np
import cv2

cv2.setNumThreads(1)
g = (np.random.rand(360, 640) * 255).astype(np.uint8)
c = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


def t(f, n=15):
    f()
    t0 = time.time()
    for _ in range(n):
        f()
    return (time.time() - t0) / n * 1000


print("gray imencode q80: %.1f ms" % t(lambda: cv2.imencode(".jpg", g, [cv2.IMWRITE_JPEG_QUALITY, 80])))
print("bgr  imencode q80: %.1f ms" % t(lambda: cv2.imencode(".jpg", c, [cv2.IMWRITE_JPEG_QUALITY, 80])))
print("gray resize 1/3:  %.1f ms" % t(lambda: cv2.resize(g, (213, 120), interpolation=cv2.INTER_AREA)))
print("slice 1/3:        %.1f ms" % t(lambda: g[::3, ::3]))
print("gray resize 1/2:  %.1f ms" % t(lambda: cv2.resize(g, (320, 180), interpolation=cv2.INTER_AREA)))
