#!/bin/sh
# 给 /etc/init.d/ip2demo 的 cam_pipe 启动行加上时域差分参数（幂等）
F=/etc/init.d/ip2demo
cp $F /root/ip2_backup/ip2demo.bak2 2>/dev/null
if grep -q 'motion-frac' $F; then
  echo "already patched"
else
  sed -i 's/--port 8080 >>/--port 8080 --motion-frac 0.12 >>/' $F
  echo "patched"
fi
grep -n 'cam_pipe.py' $F | head -3
sh -n $F && echo SYNTAX_OK
