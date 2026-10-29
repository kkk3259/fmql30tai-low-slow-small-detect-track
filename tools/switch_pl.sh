#!/bin/sh
# switch_pl.sh —— 在板子上切换 PL 位流（我们自研 IP 的不同构建）
#
# 用法:
#   ./switch_pl.sh list           # 列出可用固件与 md5
#   ./switch_pl.sh use ours       # 调参版（K=1 / MAX_AREA=2047 / area 16 位）
#   ./switch_pl.sh use merged     # A 的合并版（含 AI_Mate，我们 IP 在 0x43C00000）
#   ./switch_pl.sh use se21       # SE=21 旧版（K=4 / MAX_AREA=200）
#   ./switch_pl.sh use <文件名>   # 直接用 /lib/firmware 下某个 .bin
#
# 注意：写 fpga_manager 会让 PL 重新配置，最好先停服务（本脚本会做）。
set -e
FW=/lib/firmware
FWM=/sys/class/fpga_manager/fpga0
TARGET=$FW/ip2_bd_wrapper.bin

OURS=$FW/ip2_retune_load.bin
MERGED=$FW/ip2_merged_load.bin
SE21=$FW/ip2_se21_backup.bin

case "$1" in
  list)
    ls -l $FW/ip2*.bin 2>/dev/null || true
    md5sum $FW/ip2*.bin 2>/dev/null || true
    exit 0
    ;;
  use)
    case "$2" in
      ours)   SRC=$OURS ;;
      merged) SRC=$MERGED ;;
      se21)   SRC=$SE21 ;;
      *)      SRC=$FW/$2 ;;
    esac
    [ -f "$SRC" ] || { echo "找不到固件: $SRC"; exit 1; }
    echo "== 切换 PL 位流 -> $SRC =="
    md5sum "$SRC"
    echo "-- 停服务 --"
    /etc/init.d/ip2demo stop 2>/dev/null || true
    pkill -f 'cam_pipe[.]py' 2>/dev/null || true
    sleep 2
    echo "-- 拷贝并加载 --"
    cp -f "$SRC" "$TARGET"
    echo ip2_bd_wrapper.bin > $FWM/firmware
    sleep 1
    echo "state=$(cat $FWM/state)"
    echo "-- 起服务 --"
    /etc/init.d/ip2demo start 2>/dev/null || true
    ;;
  *)
    echo "用法: $0 {list|use ours|merged|se21|<文件名>}"
    exit 1
    ;;
esac
