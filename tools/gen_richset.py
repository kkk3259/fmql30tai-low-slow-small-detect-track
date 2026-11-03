"""丰富测试集：每帧 15+ 目标（无人机/鸟/飞机/气球/昆虫剪影），明暗混合，尺寸 3~40px。
输出 D:\firstharness\dl\richset\{name}.mp4 / .json / {name}_gt.jpg（真值标注图）"""
import os, json, math
import numpy as np, cv2

W, H = 640, 360
OUT = r"D:\firstharness\dl\richset"
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(7)


def fbm(h, w, scale, octaves, seed):
    r = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32); amp = 1.0
    for o in range(octaves):
        gw, gh = max(2, int(w / scale / (2 ** o))), max(2, int(h / scale / (2 ** o)))
        out += amp * cv2.resize(r.random((gh, gw)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
        amp *= 0.5
    out -= out.min()
    return out / max(out.max(), 1e-6)


def bg(seed, mode="sky"):
    if mode == "night":
        base = np.linspace(20, 44, H, np.float32)[:, None] * np.ones((1, W), np.float32)
        c = fbm(H, W, 80, 3, seed) * 10
    elif mode == "city":
        base = np.linspace(70, 120, H, np.float32)[:, None] * np.ones((1, W), np.float32)
        c = fbm(H, W, 40, 4, seed) * 45
    else:
        base = np.linspace(120, 205, H, np.float32)[:, None] * np.ones((1, W), np.float32)
        c = (fbm(H, W, 60, 4, seed) ** 2) * 70
    img = base + c + np.random.default_rng(seed + 5).normal(0, 3, (H, W))
    return np.clip(img, 0, 255)


KINDS = ["drone", "bird", "plane", "balloon", "insect"]


def shape_pts(kind, b):
    if kind == "drone":
        return [(-1.0 * b, -0.6 * b), (1.0 * b, -0.6 * b), (1.0 * b, 0.6 * b), (-1.0 * b, 0.6 * b),
                (-0.65 * b, -0.95 * b), (0.65 * b, -0.95 * b), (0.65 * b, 0.95 * b), (-0.65 * b, 0.95 * b)]
    if kind == "plane":
        return [(-1.0 * b, 0), (-0.1 * b, -0.35 * b), (0.95 * b, -0.95 * b), (0.15 * b, -0.1 * b),
                (1.0 * b, 0.05 * b), (0.1 * b, 0.2 * b), (0.5 * b, 0.9 * b), (-0.4 * b, 0.2 * b)]
    if kind == "balloon":
        return [(-0.8 * b, 0), (-0.3 * b, -0.9 * b), (0.3 * b, -0.9 * b), (0.8 * b, 0),
                (0.35 * b, 0.8 * b), (-0.35 * b, 0.8 * b)]
    if kind == "insect":
        return [(-0.3 * b, 0), (-0.3 * b, -1.0 * b), (0.3 * b, -1.0 * b), (0.3 * b, 0),
                (0.3 * b, 1.0 * b), (-0.3 * b, 1.0 * b)]
    # bird
    return [(-1.0 * b, 0), (-0.35 * b, -0.15 * b), (0.55 * b, -1.0 * b), (0.15 * b, -0.1 * b),
            (1.0 * b, 0.1 * b), (0.1 * b, 0.18 * b), (0.35 * b, 0.9 * b), (-0.4 * b, 0.15 * b)]


def draw(img, cx, cy, size, contrast, dark, rot, blur, kind):
    s = 8
    pad = int(size * 2.4) + 10
    canvas = np.zeros((pad * s, pad * s), np.float32)
    b = size / 2.0
    pts = shape_pts(kind, b)
    ca, sa = math.cos(rot), math.sin(rot)
    p = [((x * ca - y * sa) * s + pad * s / 2, (x * sa + y * ca) * s + pad * s / 2) for x, y in pts]
    cv2.fillPoly(canvas, [np.array(p, np.int32)], 1.0)
    k = max(1, int(blur * s))
    canvas = cv2.GaussianBlur(canvas, (k * 2 + 1, k * 2 + 1), blur * s / 2)
    canvas = cv2.resize(canvas, (pad, pad), interpolation=cv2.INTER_AREA)
    x0, y0 = int(cx - pad / 2), int(cy - pad / 2)
    x1, y1, x2, y2 = max(0, x0), max(0, y0), min(W, x0 + pad), min(H, y0 + pad)
    if x2 <= x1 or y2 <= y1:
        return
    patch = canvas[y1 - y0:y2 - y0, x1 - x0:x2 - x0]
    src = img[y1:y2, x1:x2]
    v = src - contrast if dark else src + contrast
    img[y1:y2, x1:x2] = src * (1 - patch) + np.clip(v, 0, 255) * patch


SCENES = [
    dict(name="rich_sky_20", mode="sky", n=20, frames=60),
    dict(name="rich_cloud_18", mode="sky", n=18, frames=60),
    dict(name="rich_night_16", mode="night", n=16, frames=60),
    dict(name="rich_city_15", mode="city", n=15, frames=60),
    dict(name="rich_dense_24", mode="sky", n=24, frames=40),
]


def main():
    idx = {}
    for cfg in SCENES:
        vw = cv2.VideoWriter(os.path.join(OUT, cfg["name"] + ".mp4"),
                             cv2.VideoWriter_fourcc(*"mp4v"), 30, (W, H), False)
        seed = abs(hash(cfg["name"])) % 9999
        ts = []
        for i in range(cfg["n"]):
            kind = KINDS[rng.integers(0, len(KINDS))]
            size = float(rng.choice([3, 4, 5, 6, 8, 10, 12, 15, 18, 22, 28, 34]))
            ang = rng.uniform(0, 2 * math.pi)
            spd = rng.uniform(0.3, 1.8)
            ts.append(dict(kind=kind, size=size, x=rng.uniform(30, W - 30), y=rng.uniform(25, H - 25),
                           vx=math.cos(ang) * spd, vy=math.sin(ang) * spd,
                           rot=rng.uniform(0, math.pi), dark=int(rng.random() < 0.5),
                           contrast=float(rng.uniform(45, 105))))
        gts = []
        for f in range(cfg["frames"]):
            img = bg(seed + f // 25, cfg["mode"])
            gt = []
            for t in ts:
                t["x"] += t["vx"]; t["y"] += t["vy"]
                if t["x"] < 15 or t["x"] > W - 15: t["vx"] = -t["vx"]
                if t["y"] < 12 or t["y"] > H - 12: t["vy"] = -t["vy"]
                draw(img, t["x"], t["y"], t["size"], t["contrast"], t["dark"], t["rot"],
                     0.7 + t["size"] * 0.03, t["kind"])
                gt.append({"cx": round(t["x"], 1), "cy": round(t["y"], 1), "size": t["size"], "kind": t["kind"]})
            frame = np.clip(img, 0, 255).astype(np.uint8)
            frame = cv2.GaussianBlur(frame, (3, 3), 0.6)
            ok, enc = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
            frame = cv2.imdecode(enc, cv2.IMREAD_GRAYSCALE)
            vw.write(frame)
            gts.append({"frame": f, "targets": gt})
        vw.release()
        json.dump(dict(name=cfg["name"], bg=cfg["mode"], kind=cfg["name"], w=W, h=H, gt=gts),
                  open(os.path.join(OUT, cfg["name"] + ".json"), "w"))
        # 真值标注图（第 0 帧）
        show = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        for g in gts[0]["targets"]:
            s = max(10, int(g["size"] * 2))
            cv2.rectangle(show, (int(g["cx"] - s / 2), int(g["cy"] - s / 2)),
                          (int(g["cx"] + s / 2), int(g["cy"] + s / 2)), (0, 255, 0), 1)
            cv2.putText(show, "%s%.0f" % (g["kind"][:1], g["size"]), (int(g["cx"] + s / 2), int(g["cy"])),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 200, 255), 1)
        cv2.imwrite(os.path.join(OUT, cfg["name"] + "_gt.jpg"), show)
        idx[cfg["name"]] = cfg["n"]
        print("生成", cfg["name"], cfg["n"], "个目标 x", cfg["frames"], "帧")
    json.dump(idx, open(os.path.join(OUT, "index.json"), "w"), indent=1)
    print("完成 ->", OUT)


if __name__ == "__main__":
    main()
