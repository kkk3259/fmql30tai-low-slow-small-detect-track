# patch_latency.py —— 在帧上打采集时间戳，统计“采集→编码完成”时延，并显示在 HUD
import io

p = r"D:\firstharness\repo\ps\cam_pipe.py"
s = io.open(p, encoding="utf-8").read()

# 捕获线程：给 slot 带上采集时间戳
s = s.replace("            self.slot = (f, gray)",
              "            self.slot = (f, gray, time.time())")
s = s.replace("            color, gray = item",
              "            color, gray, t_cap = item")

# 推理线程：算出“采集→本帧画完”的时延（含排队 + PL），放在画框之前
old = '            npass = sum(1 for c in cands if int(c["peak"]) >= Tracker.PEAK_MIN)'
new = ('            npass = sum(1 for c in cands if int(c["peak"]) >= Tracker.PEAK_MIN)\n'
       '            lat_ms = (time.time() - t_cap) * 1000.0\n'
       '            self.lat_ms = 0.8 * getattr(self, "lat_ms", lat_ms) + 0.2 * lat_ms')
assert old in s, "npass 行未找到"
s = s.replace(old, new)

# HUD 加时延
s = s.replace('''            cv2.putText(disp, "PL %.1fms  raw %d  stable %d  cap %.1fms %d fps" %
                        (self.pl_ms, npass, len(shown), self.cap_ms, self.pl_fps()),''',
              '''            cv2.putText(disp, "PL %.1fms  lat %.0fms  raw %d  stable %d  cap %.1fms %d fps" %
                        (self.pl_ms, self.lat_ms, npass, len(shown), self.cap_ms, self.pl_fps()),''')

# g_info 加时延
s = s.replace('            g_info.update({"cands": shown, "raw": npass, "stable": len(shown),',
              '            g_info.update({"cands": shown, "raw": npass, "stable": len(shown),\n'
              '                           "lat_ms": round(self.lat_ms, 1),')

io.open(p, "w", encoding="utf-8").write(s)
print("patched OK")
