# patch_gray.py —— 灰度推流：省一半编码时间（BGR 30ms -> GRAY 16ms），画面全分辨率更锐
import io

p = r"D:\firstharness\repo\ps\cam_pipe.py"
s = io.open(p, encoding="utf-8").read()

# 1) 全局开关
s = s.replace("LAG_FRAMES = 3.0      # 速度外推帧数（补偿端到端时延；0=不外推）",
              "LAG_FRAMES = 3.0      # 速度外推帧数（补偿端到端时延；0=不外推）\n"
              "GRAY_STREAM = 1       # 1=推灰度 JPEG（编码快一倍、全分辨率更锐）；0=推彩色")

# 2) 命令行参数
s = s.replace('    ap.add_argument("--lag", type=float, default=3.0,',
              '    ap.add_argument("--gray", type=int, default=1, help="1=灰度推流(快) 0=彩色")\n'
              '    ap.add_argument("--lag", type=float, default=3.0,')
s = s.replace("    global LAG_FRAMES, CLUSTER_R, NMS_IOU",
              "    global LAG_FRAMES, CLUSTER_R, NMS_IOU, GRAY_STREAM")
s = s.replace("    LAG_FRAMES = args.lag",
              "    LAG_FRAMES = args.lag\n    GRAY_STREAM = 1 if args.gray else 0")

# 3) 画框目标切换成灰度画布
old = '''            npass = sum(1 for c in cands if int(c["peak"]) >= Tracker.PEAK_MIN)
            for t in shown:'''
new = '''            npass = sum(1 for c in cands if int(c["peak"]) >= Tracker.PEAK_MIN)
            if GRAY_STREAM:
                disp = gray if gray.ndim == 2 else cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
            else:
                disp = color
            c_box = 255 if GRAY_STREAM else (0, 255, 0)
            c_txt = 255 if GRAY_STREAM else (0, 255, 0)
            c_hud = 255 if GRAY_STREAM else (0, 255, 255)
            for t in shown:'''
assert old in s
s = s.replace(old, new)

s = s.replace('cv2.rectangle(color, (x - r, y - r), (x + r, y + r), (0, 255, 0), 2)',
              'cv2.rectangle(disp, (x - r, y - r), (x + r, y + r), c_box, 2)')
s = s.replace('''                    cv2.putText(color, lbl, (x + 6, y - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)''',
              '''                    cv2.putText(disp, lbl, (x + 6, y - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, c_txt, 1, cv2.LINE_AA)''')
s = s.replace('''            cv2.putText(color, "PL %.1fms  raw %d  stable %d  cap %.1fms %d fps" %
                        (self.pl_ms, npass, len(shown), self.cap_ms, self.pl_fps()),
                        (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)''',
              '''            cv2.putText(disp, "PL %.1fms  raw %d  stable %d  cap %.1fms %d fps" %
                        (self.pl_ms, npass, len(shown), self.cap_ms, self.pl_fps()),
                        (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, c_hud, 2, cv2.LINE_AA)''')
s = s.replace('''            with self.paint_lock:
                self.paint = color
            globals()["g_last_img"] = color   # 供 /snap 按需出高清单帧''',
              '''            with self.paint_lock:
                self.paint = disp
            globals()["g_last_img"] = disp     # 供 /snap 按需出高清单帧''')

io.open(p, "w", encoding="utf-8").write(s)
print("patched OK")
