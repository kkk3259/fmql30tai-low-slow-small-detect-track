#!/bin/bash
# gamma 扫描：同一批 v2 测试集，不同 γ，输出召回/精确对比表
# 用法（板上）： bash /root/ip2/run_gamma_sweep.sh
set -u
cd /root/ip2
OUT=/root/gamma_sweep.txt
: > $OUT
echo "gamma  scenes  recall  precision  cand/frame" | tee -a $OUT
for G in 1.0 0.20 0.12 0.08 0.05; do
    R=$(python3 -u eval_testset2.py --dir /root/testset2 --inv both --border 24 \
            --pre gamma --gamma $G --csv /tmp/g_$G.csv 2>/dev/null | grep -E "平均|AVG" | head -1)
    echo "$G  $R" | tee -a $OUT
done
echo "--- 完成，结果在 $OUT ---"
cat $OUT
