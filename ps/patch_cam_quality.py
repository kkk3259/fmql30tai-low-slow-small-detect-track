# patch_cam_quality.py —— 提升画面清晰度 + 让静态目标也能被识别
import io

p = r"D:\firstharness\repo\ps\cam_pipe.py"
s = io.open(p, encoding="utf-8").read()

# 1) 推流质量 72 -> 85
s = s.replace('ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 72])',
              'ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])')

# 2) 框线加粗 + 标签放大
s = s.replace('cv2.rectangle(color, (x - r, y - r), (x + r, y + r), (0, 255, 0), 1)',
              'cv2.rectangle(color, (x - r, y - r), (x + r, y + r), (0, 255, 0), 2)')
s = s.replace('cv2.putText(color, "%d/%d" % (t["peak"], t["hits"]), (x + 6, y - 6),\n'
              '                                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1)',
              'cv2.putText(color, "%d/%d" % (t["peak"], t["hits"]), (x + 6, y - 6),\n'
              '                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)')

# 3) 顶部 HUD 放大
s = s.replace('(6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)',
              '(6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)')

# 4) 时域差分：始终计算 mv 供跟踪器参考，但默认不过滤（静态目标也能报）
old = """            nmv = 0
            if self.prev_gray is not None and MOTION_FRAC > 0.0:
                d_all = cv2.absdiff(gray, self.prev_gray)
                kept = []
                for c in cands:
                    cx, cy = int(c["x"]), int(c["y"])
                    r = 6
                    x0, x1 = max(0, cx - r), min(W, cx + r + 1)
                    y0, y1 = max(0, cy - r), min(H, cy + r + 1)
                    if x1 <= x0 or y1 <= y0:
                        continue
                    frac = float((d_all[y0:y1, x0:x1] > MOTION_THR).mean())
                    c["mv"] = round(frac, 2)
                    if frac >= MOTION_FRAC:
                        kept.append(c)
                    else:
                        nmv += 1
                cands = kept"""
new = """            nmv = 0
            if self.prev_gray is not None:
                d_all = cv2.absdiff(gray, self.prev_gray)
                for c in cands:
                    cx, cy = int(c["x"]), int(c["y"])
                    r = 6
                    x0, x1 = max(0, cx - r), min(W, cx + r + 1)
                    y0, y1 = max(0, cy - r), min(H, cy + r + 1)
                    if x1 <= x0 or y1 <= y0:
                        c["mv"] = 0.0
                        continue
                    c["mv"] = round(float((d_all[y0:y1, x0:x1] > MOTION_THR).mean()), 2)
                if MOTION_FRAC > 0.0:
                    kept = [c for c in cands if c.get("mv", 0.0) >= MOTION_FRAC]
                    nmv = len(cands) - len(kept)
                    cands = kept"""
assert old in s, "motion 段未匹配"
s = s.replace(old, new)

io.open(p, "w", encoding="utf-8").write(s)
print("patched OK")
