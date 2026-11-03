import time
import numpy as np
import cv2

cv2.setNumThreads(1)
img = (np.random.rand(360, 640, 3) * 255).astype(np.uint8)


def t(fn, n=20):
    fn()
    t0 = time.time()
    for _ in range(n):
        fn()
    return (time.time() - t0) / n * 1000


print("imencode q95: %.1f ms" % t(lambda: cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])))
print("imencode q85: %.1f ms" % t(lambda: cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])))
print("imencode q80: %.1f ms" % t(lambda: cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])))
print("imencode q72: %.1f ms" % t(lambda: cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 72])))
small = cv2.resize(img, (640 // 3, 360 // 3), interpolation=cv2.INTER_AREA)
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
print("cvtColor gray: %.1f ms" % t(lambda: cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)))
print("resize 1/3: %.1f ms" % t(lambda: cv2.resize(img, (640 // 3, 360 // 3), interpolation=cv2.INTER_AREA)))
print("upscale 1/3->full: %.1f ms" % t(lambda: cv2.resize(small, (640, 360), interpolation=cv2.INTER_LINEAR)))
print("draw 8 rects+text: %.1f ms" % t(lambda: [cv2.rectangle(img, (10 + i * 20, 10), (30 + i * 20, 30), (0, 255, 0), 2) for i in range(8)]))
print("cv2.getBuildInformation threads:", cv2.getNumThreads())
