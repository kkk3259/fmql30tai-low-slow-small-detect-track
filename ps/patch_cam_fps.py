# patch_cam_fps.py —— 提帧率：多尺度第二遍隔帧做 + 推流质量 85->80
import io

p = r"D:\firstharness\repo\ps\cam_pipe.py"
s = io.open(p, encoding="utf-8").read()

# 1) 质量 85 -> 80
s = s.replace('ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])',
              'ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])')

# 2) 多尺度第二遍支持隔帧（MS_EVERY）
s = s.replace("MS_FACTOR2 = 0        # 第三遍倍数（4 => 补 20~80px；0=关闭，会再慢 1/3）",
              "MS_FACTOR2 = 0        # 第三遍倍数（4 => 补 20~80px；0=关闭，会再慢 1/3）\n"
              "MS_EVERY = 1          # 多尺度第二/三遍每 N 帧做一次（2 => 隔帧，省一半 PL 时间）\n"
              "MS_CNT = 0            # 帧计数")

old_run_ms_head = '        st, c1, dt = self.run(gray)\n        out = list(c1)\n        total = dt\n        for n in (MS_FACTOR, MS_FACTOR2):\n            if n < 2:\n                continue'
new_run_ms_head = ('        global MS_CNT\n'
                   '        st, c1, dt = self.run(gray)\n'
                   '        out = list(c1)\n'
                   '        total = dt\n'
                   '        MS_CNT += 1\n'
                   '        do_extra = (MS_EVERY <= 1) or (MS_CNT % MS_EVERY == 0)\n'
                   '        for n in ((MS_FACTOR, MS_FACTOR2) if do_extra else ()):\n'
                   '            if n < 2:\n'
                   '                continue')
assert old_run_ms_head in s, "run_ms 头部未匹配"
s = s.replace(old_run_ms_head, new_run_ms_head)

# 3) 参数与全局
s = s.replace("    global MOTION_FRAC, MOTION_THR, MULTI_SCALE, MS_FACTOR, MS_FACTOR2",
              "    global MOTION_FRAC, MOTION_THR, MULTI_SCALE, MS_FACTOR, MS_FACTOR2, MS_EVERY")
s = s.replace("    MS_FACTOR2 = args.ms_factor2",
              "    MS_FACTOR2 = args.ms_factor2\n    MS_EVERY = args.ms_every")
s = s.replace('    ap.add_argument("--ms-factor2", type=int, default=0, help="多尺度第三遍倍数（4 => 补 20~80px；0=关闭）")',
              '    ap.add_argument("--ms-factor2", type=int, default=0, help="多尺度第三遍倍数（4 => 补 20~80px；0=关闭）")\n'
              '    ap.add_argument("--ms-every", type=int, default=1, help="多尺度第二/三遍每 N 帧做一次（2=隔帧，省一半 PL 时间）")')

io.open(p, "w", encoding="utf-8").write(s)
print("patched OK")
