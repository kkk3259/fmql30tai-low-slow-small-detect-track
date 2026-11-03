#!/bin/sh
echo "=== video 设备 ==="
ls -l /dev/video* 2>/dev/null
echo "=== python 模块 ==="
python3 - <<'EOF'
mods = ["cv2", "numpy", "PIL"]
for m in mods:
    try:
        mod = __import__(m)
        print(m, "OK", getattr(mod, "__version__", ""))
    except Exception as e:
        print(m, "MISSING", e)
EOF
echo "=== v4l2-ctl ==="
which v4l2-ctl
v4l2-ctl --list-formats-ext -d /dev/video0 2>&1 | head -30
echo "=== 相机信息 ==="
cat /sys/class/video4linux/video0/name 2>/dev/null
lsusb 2>/dev/null | head -5
