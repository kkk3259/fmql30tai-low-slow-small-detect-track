# patch_tracker_fast.py —— 跟踪器提速 + 标签换成“编号/尺寸/速度”
import io
import re

p = r"D:\firstharness\repo\ps\cam_pipe.py"
s = io.open(p, encoding="utf-8").read()

start = s.index("class Tracker(object):")
end = s.index("class Pipeline(object):")
new_cls = '''class Tracker(object):
    """跨帧候选跟踪 + 去抖。

    规则：
      * 同一目标在相邻帧位置差 <= MATCH_R 视为同一条 track（坐标/面积/峰值做到 EMA 平滑）
      * 连续命中 >= MIN_HITS 帧才对外显示
      * 连续丢失 > MAX_MISS 帧才移除
      * 每条 track 维护 vx/vy（像素/帧），用于在画面上标速度
    性能：候选按峰值预剪（MAX_IN），track 池上限 MAX_TRACKS，避免 O(候选×track) 爆炸。
    """

    MATCH_R = 12       # 匹配半径（像素，棋盘距离）
    MIN_HITS = 2       # 命中多少帧才显示
    MAX_MISS = 10      # 连续丢失多少帧才删除
    MAX_SHOW = 64      # 最多显示多少个
    PEAK_MIN = 0       # 候选峰值下限
    MAX_IN = 48        # 每帧最多送进跟踪的候选数（按峰值排序取前 N）
    MAX_TRACKS = 160   # track 池上限

    def __init__(self):
        self.tracks = []
        self.next_id = 1

    def update(self, cands, fps=25.0):
        # 1) 候选预剪：按 (mv, peak) 排序，只保留前 MAX_IN 个
        cs = sorted(cands, key=lambda c: (-float(c.get("mv", 0.0)), -int(c["peak"])))[:self.MAX_IN]
        nt = len(self.tracks)
        used = [False] * nt
        for c in cs:
            if int(c["peak"]) < self.PEAK_MIN:
                continue
            cx, cy = int(c["x"]), int(c["y"])
            best, bestd = -1, 10 ** 9
            for i in range(nt):
                if used[i]:
                    continue
                t = self.tracks[i]
                d = max(abs(t["x"] - cx), abs(t["y"] - cy))
                if d <= self.MATCH_R and d < bestd:
                    best, bestd = i, d
            if best >= 0:
                t = self.tracks[best]
                used[best] = True
                dx, dy = cx - t["x"], cy - t["y"]
                t["x"] = (4 * t["x"] + cx) // 5
                t["y"] = (4 * t["y"] + cy) // 5
                t["area"] = (4 * t["area"] + int(c["area"])) // 5
                t["peak"] = (4 * t["peak"] + int(c["peak"])) // 5
                t["vx"] = 0.6 * t.get("vx", 0.0) + 0.4 * dx
                t["vy"] = 0.6 * t.get("vy", 0.0) + 0.4 * dy
                t["hits"] += 1
                t["miss"] = 0
            else:
                self.tracks.append({"id": self.next_id, "x": cx, "y": cy,
                                    "area": int(c["area"]), "peak": int(c["peak"]),
                                    "vx": 0.0, "vy": 0.0,
                                    "hits": 1, "miss": 0})
                self.next_id += 1
        # 2) 未匹配的 track 衰减
        keep = []
        for i, t in enumerate(self.tracks):
            if i < nt and not used[i]:
                t["miss"] += 1
                t["vx"] *= 0.5
                t["vy"] *= 0.5
                if t["hits"] > 1:
                    t["hits"] -= 1
            if t["miss"] <= self.MAX_MISS:
                keep.append(t)
        # 3) 池上限：优先保留命中多、丢失少的
        if len(keep) > self.MAX_TRACKS:
            keep.sort(key=lambda t: (-t["hits"], t["miss"]))
            keep = keep[:self.MAX_TRACKS]
        self.tracks = keep
        conf = [t for t in self.tracks if t["hits"] >= self.MIN_HITS]
        conf.sort(key=lambda t: (-t["hits"], -t["peak"]))
        out = conf[:self.MAX_SHOW]
        for t in out:
            t["spd"] = int((t.get("vx", 0.0) ** 2 + t.get("vy", 0.0) ** 2) ** 0.5 * fps)
        return out


'''
s = s[:start] + new_cls + s[end:]

# 调用处：传 fps + 标签换成 #编号 尺寸px 速度
s = s.replace('shown = self.tracker.update(cands)',
              'shown = self.tracker.update(cands, self.pl_fps())')
old_lbl = ('                if x < W - 40 and y > 10:\n'
           '                    cv2.putText(color, "%d/%d" % (t["peak"], t["hits"]), (x + 6, y - 6),\n'
           '                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)')
new_lbl = ('                side = max(1, int(round((t["area"]) ** 0.5)))\n'
           '                spd = t.get("spd", 0)\n'
           '                lbl = "#%d %dpx" % (t["id"] % 100, side)\n'
           '                if spd >= 8:\n'
           '                    lbl += " %d/s" % spd\n'
           '                if x < W - 60 and y > 10:\n'
           '                    cv2.putText(color, lbl, (x + 6, y - 6),\n'
           '                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)')
assert old_lbl in s, "标签段未匹配"
s = s.replace(old_lbl, new_lbl)

io.open(p, "w", encoding="utf-8").write(s)
print("patched OK")
