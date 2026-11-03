#!/bin/sh
S=/sys/class/u-dma-buf/udmabuf0
for f in sync_mode sync_direction sync_offset sync_size sync_owner sync_for_device sync_for_cpu dma_coherent driver_version; do
  printf '%-16s = ' "$f"; cat "$S/$f" 2>/dev/null
done
echo "--- write sync_mode=0 ---"
if echo 0 > "$S/sync_mode" 2>/dev/null; then echo "write ok"; else echo "write FAILED"; fi
printf 'sync_mode now = '; cat "$S/sync_mode"
echo "--- 各属性的用法提示（如果存在） ---"
ls /sys/class/u-dma-buf/udmabuf0/ | tr '\n' ' '
echo
