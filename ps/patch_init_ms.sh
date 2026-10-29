#!/bin/sh
# 给 /etc/init.d/ip2demo 的 cam_pipe 启动行加 --multi-scale 1（幂等）
F=/etc/init.d/ip2demo
if grep -q 'multi-scale' $F; then
  echo "already patched"
else
  sed -i 's/--port 8080 --motion-frac 0.12 >>/--port 8080 --motion-frac 0.12 --multi-scale 1 >>/' $F
  echo "patched"
fi
grep -n 'cam_pipe.py' $F | head -3
sh -n $F && echo SYNTAX_OK
