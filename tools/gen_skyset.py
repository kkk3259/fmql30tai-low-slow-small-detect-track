"""天空小目标专用测试集：只做比赛场景（天空/云/夜空），目标 3~40px，明暗都有。
输出 ./data/skyset\<name>.mp4 + .json（逐帧真值）"""
import os, json, math
import numpy as np, cv2

W, H, N = 640, 360, 120
OUT = r"./data/skyset"
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(2025)


def fbm(h, w, scale, octaves, seed):
    r = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32)
    amp = 1.0
    for o in range(octaves):
        gw, gh = max(2, int(w / scale / (2 ** o))), max(2, int(h / scale / (2 ** o)))
        g = r.random((gh, gw)).astype(np.float32)
        out += amp * cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC)
        amp *= 0.5
    out -= out.min()
    return out / max(out.max(), 1e-6)


def bg_sky(seed, clouds=0.6, night=False):
    grad = np.linspace(120, 205, H, dtype=np.float32)[:, None] * np.ones((1, W), np.float32)
    if night:
        grad = np.linspace(22, 46, H, dtype=np.float32)[:, None] * np.ones((1, W), np.float32)
    img = grad.copy()
    if clouds > 0:
        c = fbm(H, W, 60, 4, seed)
        img += (c ** 2) * (70 if not night else 12) * clouds
    img += np.random.default_rng(seed + 1).normal(0, 3 if not night else 7, (H, W))
    return np.clip(img, 0, 255)


def draw_target(img, cx, cy, size, contrast, dark, rot, blur):
    """画鸟形剪影（两翼+身），超采样后缩小"""
    s = 8
    pad = int(size * 2.2) + 8
    canvas = np.zeros((pad * s, pad * s), np.float32)
    b = size / 2.0
    pts = [(-1.0 * b, 0), (-0.35 * b, -0.15 * b), (0.55 * b, -1.0 * b), (0.15 * b, -0.1 * b),
           (1.0 * b, 0.1 * b), (0.1 * b, 0.18 * b), (0.35 * b, 0.9 * b), (-0.4 * b, 0.15 * b)]
    ca, sa = math.cos(rot), math.sin(rot)
    p = [((x * ca - y * sa) * s + pad * s / 2, (x * sa + y * ca) * s + pad * s / 2) for x, y in pts]
    cv2.fillPoly(canvas, [np.array(p, np.int32)], 1.0)
    k = max(1, int(blur * s))
    canvas = cv2.GaussianBlur(canvas, (k * 2 + 1, k * 2 + 1), blur * s / 2)
    canvas = cv2.resize(canvas, (pad, pad), interpolation=cv2.INTER_AREA)
    x0, y0 = int(cx - pad / 2), int(cy - pad / 2)
    x1, y1 = max(0, x0), max(0, y0)
    x2, y2 = min(W, x0 + pad), min(H, y0 + pad)
    if x2 <= x1 or y2 <= y1:
        return
    patch = canvas[y1 - y0:y2 - y0, x1 - x0:x2 - x0]
    src = img[y1:y2, x1:x2]
    v = src - contrast if dark else src + contrast
    img[y1:y2, x1:x2] = src * (1 - patch) + np.clip(v, 0, 255) * patch


SCENES = {
    "sky_dark_5":   dict(bg=dict(clouds=0.2), sizes=[5], dark=[1], contrast=[90]),
    "sky_dark_12":  dict(bg=dict(clouds=0.3), sizes=[12], dark=[1], contrast=[80]),
    "sky_dark_24":  dict(bg=dict(clouds=0.3), sizes=[24], dark=[1], contrast=[70]),
    "sky_dark_40":  dict(bg=dict(clouds=0.3), sizes=[40], dark=[1], contrast=[60]),
    "sky_bright_5": dict(bg=dict(clouds=0.9), sizes=[5], dark=[0], contrast=[90]),
    "sky_bright_18": dict(bg=dict(clouds=0.9), sizes=[18], dark=[0], contrast=[80]),
    "cloud_dark_10": dict(bg=dict(clouds=1.0), sizes=[10], dark=[1], contrast=[75]),
    "cloud_dark_30": dict(bg=dict(clouds=1.0), sizes=[30], dark=[1], contrast=[65]),
    "night_dark_8": dict(bg=dict(clouds=0.1, night=True), sizes=[8], dark=[0], contrast=[70]),
    "night_dark_20": dict(bg=dict(clouds=0.1, night=True), sizes=[20], dark=[0], contrast=[60]),
    "sky_multi":    dict(bg=dict(clouds=0.5), sizes=[6, 10, 16, 26], dark=[1, 1, 0, 1], contrast=[85, 75, 70, 65]),
    "sky_tiny":     dict(bg=dict(clouds=0.4), sizes=[3, 4, 6], dark=[1, 1, 1], contrast=[110, 100, 90]),
}


def main():
    idx = {}
    for name, cfg in SCENES.items():
        vw = cv2.VideoWriter(os.path.join(OUT, name + ".mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 30, (W, H), False)
        gts = []
        seed = abs(hash(name)) % 10000
        n_t = len(cfg["sizes"])
        # 每个目标一条匀速直线
        trk = []
        for i in range(n_t):
            ang = rng.uniform(0, 2 * math.pi)
            spd = rng.uniform(0.6, 2.2)
            trk.append(dict(x=rng.uniform(60, W - 60), y=rng.uniform(50, H - 50),
                            vx=math.cos(ang) * spd, vy=math.sin(ang) * spd,
                            rot=rng.uniform(0, math.pi), blur=0.8 + cfg["sizes"][i] * 0.03))
        for f in range(N):
            img = bg_sky(seed + f // 40, **cfg["bg"])
            gt = []
            for i, t in enumerate(trk):
                t["x"] += t["vx"]
                t["y"] += t["vy"]
                if t["x"] < 40 or t["x"] > W - 40: t["vx"] = -t["vx"]
                if t["y"] < 30 or t["y"] > H - 30: t["vy"] = -t["vy"]
                draw_target(img, t["x"], t["y"], cfg["sizes"][i], cfg["contrast"][i],
                            cfg["dark"][i] == 1, t["rot"], t["blur"])
                gt.append([round(t["x"], 1), round(t["y"], 1), cfg["sizes"][i]])
            frame = np.clip(img, 0, 255).astype(np.uint8)
            frame = cv2.GaussianBlur(frame, (3, 3), 0.6)
            ok, enc = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
            vw.write(cv2.imdecode(enc, cv2.IMREAD_GRAYSCALE))
            gts.append(gt)
        vw.release()
        json.dump({"name": name, "w": W, "h": H, "frames": gts}, open(os.path.join(OUT, name + ".json"), "w"))
        idx[name] = dict(sizes=cfg["sizes"], dark=cfg["dark"], contrast=cfg["contrast"])
        print("生成", name, cfg["sizes"], cfg["dark"])
    json.dump(idx, open(os.path.join(OUT, "index.json"), "w"), ensure_ascii=False, indent=1)
    print("完成 ->", OUT)


if __name__ == "__main__":
    main()
