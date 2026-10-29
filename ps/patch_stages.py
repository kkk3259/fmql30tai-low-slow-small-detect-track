# patch_stages.py —— 只加跟踪段计时（trk_ms），其余用 lat - PL - trk 推算
import io

p = r"D:\firstharness\repo\ps\cam_pipe.py"
s = io.open(p, encoding="utf-8").read()

old = "            shown = nms_tracks(self.tracker.update(cands, self.pl_fps()), NMS_IOU)"
assert old in s, "调用行未找到"
s = s.replace(old,
              "            _t0 = time.time()\n" + old + "\n"
              "            self.trk_ms = 0.8 * getattr(self, \"trk_ms\", 0.0) + 0.2 * (time.time() - _t0) * 1000.0")

s = s.replace('"lat_ms": round(self.lat_ms, 1),',
              '"lat_ms": round(self.lat_ms, 1),\n'
              '                           "trk_ms": round(getattr(self, "trk_ms", 0.0), 1),')

io.open(p, "w", encoding="utf-8").write(s)
print("patched OK")
