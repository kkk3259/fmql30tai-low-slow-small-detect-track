# patch_dedup_lag.py —— 候选聚类 + 框去重(NMS) + 速度外推(补偿时延)
import io

p = r"D:\firstharness\repo\ps\cam_pipe.py"
s = io.open(p, encoding="utf-8").read()

# ---------- 1) 新增全局参数 ----------
s = s.replace("MS_CNT = 0            # 帧计数",
              "MS_CNT = 0            # 帧计数\n"
              "CLUSTER_R = 12        # 候选聚类半径（像素）：相距小于它的候选合并成一个目标\n"
              "NMS_IOU = 0.45        # 框去重阈值：交叠/较小框面积 超过它就合并\n"
              "LAG_FRAMES = 3.0      # 速度外推帧数（补偿端到端时延；0=不外推）")

# ---------- 2) 候选聚类函数（放在 Tracker 类之前） ----------
anchor = "class Tracker(object):"
cluster_fn = '''def cluster_cands(cands, r=12):
    """把相距 < r 的候选合并成一个（按面积加权质心），避免同一目标出多个框。"""
    if len(cands) <= 1:
        return cands
    out = []
    for c in sorted(cands, key=lambda c: -int(c["area"])):
        cx, cy, ar = int(c["x"]), int(c["y"]), max(1, int(c["area"]))
        merged = False
        for o in out:
            if abs(o["x"] - cx) <= r and abs(o["y"] - cy) <= r:
                w = o["_w"]
                o["x"] = int((o["x"] * w + cx * ar) / (w + ar))
                o["y"] = int((o["y"] * w + cy * ar) / (w + ar))
                o["area"] = min(60000, o["area"] + ar)
                o["_w"] = w + ar
                o["peak"] = max(int(o["peak"]), int(c["peak"]))
                o["mv"] = max(float(o.get("mv", 0.0)), float(c.get("mv", 0.0)))
                merged = True
                break
        if not merged:
            d = dict(c)
            d["_w"] = ar
            out.append(d)
    for o in out:
        o.pop("_w", None)
    return out


def nms_tracks(trks, iom=0.45):
    """框去重：交叠/较小框面积 超过 iom 的视为同一个目标，保留命中多的。"""
    keep = []
    for t in sorted(trks, key=lambda t: (-t["hits"], -int(t["area"]))):
        r0 = max(4, int((int(t["area"]) ** 0.5) / 2) + 3)
        x0, y0 = int(t["x"]), int(t["y"])
        drop = False
        for k in keep:
            r1 = max(4, int((int(k["area"]) ** 0.5) / 2) + 3)
            x1, y1 = int(k["x"]), int(k["y"])
            ox = max(0, min(x0 + r0, x1 + r1) - max(x0 - r0, x1 - r1))
            oy = max(0, min(y0 + r0, y1 + r1) - max(y0 - r0, y1 - r1))
            inter = ox * oy
            a0 = (2 * r0 + 1) ** 2
            a1 = (2 * r1 + 1) ** 2
            if inter > 0 and inter / float(min(a0, a1)) > iom:
                drop = True
                break
        if not drop:
            keep.append(t)
    return keep


'''
s = s.replace(anchor, cluster_fn + anchor, 1)

# ---------- 3) 推理线程里：先聚类，再跟踪，再去重，画在预测位置 ----------
s = s.replace("            shown = self.tracker.update(cands, self.pl_fps())",
              "            cands = cluster_cands(cands, CLUSTER_R)\n"
              "            shown = nms_tracks(self.tracker.update(cands, self.pl_fps()), NMS_IOU)")

old_draw = ('            for t in shown:\n'
            '                x, y = int(t["x"]), int(t["y"])')
new_draw = ('            for t in shown:\n'
            '                # 速度外推：往前推 LAG_FRAMES 帧，抵消端到端时延，让框盖在目标身上\n'
            '                x = int(t["x"] + t.get("vx", 0.0) * LAG_FRAMES)\n'
            '                y = int(t["y"] + t.get("vy", 0.0) * LAG_FRAMES)\n'
            '                x = max(0, min(W - 1, x))\n'
            '                y = max(0, min(H - 1, y))')
assert old_draw in s, "画框段未匹配"
s = s.replace(old_draw, new_draw)

# ---------- 4) 命令行参数 ----------
s = s.replace('    ap.add_argument("--ms-every", type=int, default=1,',
              '    ap.add_argument("--lag", type=float, default=3.0, help="速度外推帧数（补偿时延，0=关闭）")\n'
              '    ap.add_argument("--cluster-r", type=int, default=12, help="候选聚类半径（像素）")\n'
              '    ap.add_argument("--nms-iou", type=float, default=0.45, help="框去重阈值")\n'
              '    ap.add_argument("--ms-every", type=int, default=1,')
s = s.replace("    global MOTION_FRAC, MOTION_THR, MULTI_SCALE, MS_FACTOR, MS_FACTOR2, MS_EVERY",
              "    global MOTION_FRAC, MOTION_THR, MULTI_SCALE, MS_FACTOR, MS_FACTOR2, MS_EVERY\n"
              "    global LAG_FRAMES, CLUSTER_R, NMS_IOU")
s = s.replace("    MS_EVERY = args.ms_every",
              "    MS_EVERY = args.ms_every\n"
              "    LAG_FRAMES = args.lag\n"
              "    CLUSTER_R = args.cluster_r\n"
              "    NMS_IOU = args.nms_iou")

io.open(p, "w", encoding="utf-8").write(s)
print("patched OK")
