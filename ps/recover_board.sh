#!/bin/bash
# 板子恢复：加载已知可用的检测器位流并重启网页服务
set +e
echo "=== 1. 加载已知可用的独立检测器位流 ==="
echo ip2_bd_wrapper.bin > /sys/class/fpga_manager/fpga0/firmware
echo "  rc=$?"
sleep 2
echo -n "  state="; cat /sys/class/fpga_manager/fpga0/state

echo "=== 2. 重启网页服务 ==="
/etc/init.d/ip2demo restart >/dev/null 2>&1
sleep 12
pgrep -af 'cam_pipe[.]py' | head -1

echo "=== 3. 检查 ==="
sleep 3
python3 - <<'EOF' 2>/dev/null
import urllib.request, json
try:
    o = json.load(urllib.request.urlopen("http://127.0.0.1:8080/info", timeout=5))
    print("  fps=%s PL=%sms raw=%s stable=%s" % (o.get("fps"), o.get("PL_ms"), o.get("raw"), o.get("stable")))
except Exception as e:
    print("  /info 失败:", str(e)[:80])
EOF
