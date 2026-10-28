# patch_cam_demo.py —— 把 cam_demo.py 改成 640x480 采集 + 上下裁 60 行（不做缩放）
import io

p = r"D:\firstharness\repo\ps\cam_demo.py"
s = io.open(p, encoding="utf-8").read()

old_cap = "    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)\n    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)"
new_cap = ("    # 640x480 采集，上下各裁 60 行得到 640x360（与 PL 链路一一对应，省掉缩放）\n"
           "    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)\n"
           "    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)")
assert old_cap in s, "cap 段未找到"
s = s.replace(old_cap, new_cap)

old_gray = ("        gray = cv2.cvtColor(cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA),\n"
            "                            cv2.COLOR_BGR2GRAY)")
new_gray = ("        fh = frame.shape[0]\n"
            "        if fh >= H:\n"
            "            top = (fh - H) // 2\n"
            "            frame = frame[top:top + H, :, :]\n"
            "        else:\n"
            "            frame = cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA)\n"
            "        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)")
assert old_gray in s, "gray 段未找到"
s = s.replace(old_gray, new_gray)

io.open(p, "w", encoding="utf-8").write(s)
print("patched OK")
