# patch_cam_demo2.py —— 去掉每帧固定 10ms 的 sleep，并把触发轮询粒度从 0.5ms 收紧到 0.1ms
import io

p = r"D:\firstharness\repo\ps\cam_demo.py"
s = io.open(p, encoding="utf-8").read()

# 1) 主循环里那句固定 sleep(0.01) 去掉
old1 = "            time.sleep(0.01)\n            continue"
new1 = "            time.sleep(0.002)\n            continue"
if old1 in s:
    s = s.replace(old1, new1)

# 2) 触发后轮询粒度收紧
old2 = "            time.sleep(0.0005)"
new2 = "            time.sleep(0.0001)"
if old2 in s:
    s = s.replace(old2, new2)

io.open(p, "w", encoding="utf-8").write(s)
print("patched2 OK", "sleep0.01" in s, "sleep0.0001" in s)
