#!/bin/bash
# board_check.sh —— 板端快速体检（板子回来后按这个顺序查）
#
# 用途：一次跑完，覆盖三域串联前的所有前置检查
#   ① PL 寄存器通路（等 P 的位流）
#   ② udmabuf 属性（71 MB/s 带宽之谜的第一步）
#   ③ NPU 设备（AI_Mate 是否在位流里）
#   ④ 摄像头
#   ⑤ DMA 基础带宽（用 dd 测内存侧，区分"内存慢"还是"NPU 的 DMA 慢"）
#
# 用法（板上 root）：
#   bash tools/board_check.sh
#   或先传到板子：scp tools/board_check.sh root@169.254.67.100:/root/
#                ssh root@169.254.67.100 "bash /root/board_check.sh"

PY=/root/pywork/probe_addr.py
[ -f "$PY" ] || PY=$(dirname "$0")/../ps/probe_addr.py

echo "=============================================="
echo " ① PL 寄存器通路（基址 0x43C00000 挂 GP0）"
echo "=============================================="
echo "  fpga0 state = $(cat /sys/class/fpga_manager/fpga0/state 2>/dev/null || echo '未知')"
for addr in 0x43C00000 0x43C00004 0x43C00014 0x83C00000; do
    printf "  %-12s → " "$addr"
    out=$(timeout 6 python3 "$PY" "$addr" 2>&1)
    rc=$?
    if [ $rc -eq 0 ] && [ -n "$out" ]; then
        echo "$out"
    else
        echo "SIGBUS (rc=$rc)"
    fi
done
echo "  期望：0x43C00014 = 0x00010000（VERSION）；SIGBUS 说明位流没加载或 AXI 没接 GP0"

echo
echo "=============================================="
echo " ② AI_Mate / NPU 是否在位流里"
echo "=============================================="
printf "  0x4000001C（AI_Mate 版本号） → "
out=$(timeout 6 python3 "$PY" 0x4000001C 2>&1)
if [ $? -eq 0 ] && [ -n "$out" ]; then echo "$out"; else echo "SIGBUS"; fi
echo "  期望：0x25122301（官方位流里 AI_Mate 正常）。"
echo "  注意：若加载了只含自研 IP 的位流，这里会 SIGBUS（NPU 就不在了）"

echo
echo "=============================================="
echo " ③ udmabuf 属性（71 MB/s 带宽之谜第一步）"
echo "=============================================="
for f in /sys/class/u-dma-buf/udmabuf0/*; do
    [ -f "$f" ] && printf "  %-30s = %s\n" "$(basename $f)" "$(cat $f 2>/dev/null)"
done
ls -l /dev/udmabuf* 2>/dev/null | sed 's/^/  /'
echo "  关注：sync_mode（0=只读/1=写/2=读写）、cacheable（1=可缓存，0=uncached）"
echo "  若 cacheable=0 且 sync_mode 保守 → PS 侧写很慢，这是 71MB/s 的常见原因"

echo
echo "=============================================="
echo " ④ 摄像头"
echo "=============================================="
ls /dev/video* 2>/dev/null | sed 's/^/  /' || echo "  无 /dev/video*（摄像头没插？）"
for d in /dev/video1 /dev/video2; do
    if [ -e "$d" ]; then
        echo "  --- $d ---"
        v4l2-ctl -d "$d" --info 2>/dev/null | grep -E "Card type|Driver name" | sed 's/^/    /'
        v4l2-ctl -d "$d" --list-formats-ext 2>/dev/null | grep -E "MJPG|1280x720|640x480" | head -5 | sed 's/^/    /'
    fi
done
echo "  注意：/dev/video0 通常是 VPU 解码设备，不是摄像头"

echo
echo "=============================================="
echo " ⑤ 内存侧基础带宽（区分内存慢 vs NPU DMA 慢）"
echo "=============================================="
echo "  写 1.2 MB（与主模型输入同量级）到 /dev/udmabuf0："
if [ -e /dev/udmabuf0 ]; then
    dd if=/dev/zero of=/dev/udmabuf0 bs=1024 count=1200 conv=fsync 2>&1 | tail -1 | sed 's/^/    /'
    echo "  ⇒ 若这里只有几十 MB/s，问题在内存/udmabuf（uncached）"
    echo "  ⇒ 若这里 GB/s 级但 NPU forward 里 DMA 只跑 71MB/s，问题在 NPU 的 DMA 引擎配置"
else
    echo "    无 /dev/udmabuf0"
fi

echo
echo "  参考：AXI HP 理论 64-bit @200MHz = 1.6 GB/s；实测 71 MB/s 差约 22 倍"

echo
echo "=============================================="
echo " ⑥ 系统状态"
echo "=============================================="
uptime | sed 's/^/  /'
free -m | sed 's/^/  /'
ip -4 addr show eth0 2>/dev/null | grep inet | sed 's/^/  /'
echo
echo "  完成。把上面输出整段发回即可定位问题。"
