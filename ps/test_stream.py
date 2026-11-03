# test_stream.py —— 从板上 /stream 连续读几帧，确认 MJPEG 流在动
import urllib.request
import re
import sys
import time

url = "http://169.254.67.100:8080/stream"
t0 = time.time()
n = 0
sizes = []
buf = b""
with urllib.request.urlopen(url, timeout=10) as r:
    print("HTTP", r.status, r.headers.get("Content-Type"))
    while n < 6 and time.time() - t0 < 12:
        chunk = r.read(4096)
        if not chunk:
            break
        buf += chunk
        while True:
            i = buf.find(b"--frame")
            j = buf.find(b"--frame", i + 7)
            if i < 0 or j < 0:
                break
            part = buf[i:j]
            m = re.search(rb"Content-Length: (\d+)", part)
            if m:
                n += 1
                sizes.append(int(m.group(1)))
            buf = buf[j:]
el = time.time() - t0
print("收到 %d 帧, 用时 %.1f 秒 → %.1f fps" % (n, el, n / max(el, 1e-6)))
print("各帧字节数:", sizes)
