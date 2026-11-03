#!/bin/sh
# run_mv.sh —— 带时域差分参数启动实时链路（试验用，正式启动仍走 /etc/init.d/ip2demo）
cd /root/ip2 || exit 1
exec python3 -u cam_pipe.py --port 8080 --motion-frac 0.12 --motion-thr 8
