# deploy_tracker.ps1 —— 把带航迹跟踪的 cam3d_pipe.py 部署到板子并验证
#
# 前置：板子已加载三域位流（ours3d_s5.bin），且 169.254.67.100 可 ping
# 用法：powershell -ExecutionPolicy Bypass -File ps\deploy_tracker.ps1
#
# 做的事：
#   1. 备份板上的原 cam3d_pipe.py（带时间戳，可回滚）
#   2. scp 上传新版
#   3. 重启 ip2d3 服务
#   4. 拉 /info 验证 ntrk 字段出现、帧率正常
#
# 回滚：ssh root@169.254.67.100 "cp /root/ip2/cam3d_pipe.py.bak.* /root/ip2/cam3d_pipe.py && /etc/init.d/ip2d3 restart"

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$BOARD = "169.254.67.100"
$REPO = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$LOCAL = Join-Path $REPO "ps\cam3d_pipe.py"
$REMOTE = "/root/ip2/cam3d_pipe.py"

Write-Host "=== 1. 检查板子 ===" -ForegroundColor Cyan
if (-not (Test-Connection -ComputerName $BOARD -Count 2 -Quiet -ErrorAction SilentlyContinue)) {
    Write-Host "  [x] $BOARD ping 不通，退出（先在板上确认三域位流已加载）" -ForegroundColor Red
    exit 1
}
Write-Host "  [ok] ping 通"

$script0 = @'
echo "  fpga state : $(cat /sys/class/fpga_manager/fpga0/state 2>/dev/null || echo NA)"
echo "  cam3d_pipe : $(pgrep -af 'cam3d_pipe[.]py' | head -1 || echo '未运行')"
echo "  远端行数   : $(wc -l < /root/ip2/cam3d_pipe.py 2>/dev/null || echo NA)"
echo "  远端 md5   : $(md5sum /root/ip2/cam3d_pipe.py 2>/dev/null | cut -c1-12 || echo NA)"
'@
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($script0))
& ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=no root@$BOARD "echo '$b64' | base64 -d | bash" 2>&1 | ForEach-Object { Write-Host ("  " + $_) }

Write-Host ""
Write-Host "=== 2. 备份 + 上传 ===" -ForegroundColor Cyan
$stamp = Get-Date -Format "MMddHHmm"
& ssh -o ConnectTimeout=8 root@$BOARD "cp $REMOTE ${REMOTE}.bak.$stamp 2>/dev/null; echo '  backed up -> ${REMOTE}.bak.$stamp'" 2>&1 | ForEach-Object { Write-Host ("  " + $_) }
& scp -o ConnectTimeout=10 $LOCAL "root@${BOARD}:$REMOTE" 2>&1 | ForEach-Object { Write-Host ("  " + $_) }

$script1 = @'
echo "  上传后 md5 : $(md5sum /root/ip2/cam3d_pipe.py | cut -c1-12)"
echo "  上传后行数 : $(wc -l < /root/ip2/cam3d_pipe.py)"
echo "  含 Tracker : $(grep -c 'class Tracker' /root/ip2/cam3d_pipe.py)"
'@
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($script1))
& ssh -o ConnectTimeout=8 root@$BOARD "echo '$b64' | base64 -d | bash" 2>&1 | ForEach-Object { Write-Host ("  " + $_) }

Write-Host ""
Write-Host "=== 3. 重启服务 ===" -ForegroundColor Cyan
$script2 = @'
/etc/init.d/ip2d3 stop >/dev/null 2>&1
sleep 2
/etc/init.d/ip2d3 start >/dev/null 2>&1
sleep 12
echo "  进程: $(pgrep -af 'cam3d_pipe[.]py' | head -1 || echo '未运行')"
echo "  日志尾:"
tail -5 /root/ip2/ip2d3.log 2>/dev/null | sed 's/^/    /'
'@
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($script2))
& ssh -o ConnectTimeout=8 root@$BOARD "echo '$b64' | base64 -d | bash" 2>&1 | ForEach-Object { Write-Host ("  " + $_) }

Write-Host ""
Write-Host "=== 4. 验证 /info（关键：ntrk 字段应出现且 > 0）===" -ForegroundColor Cyan
$script3 = @'
python3 - <<'EOF' 2>&1
import urllib.request, json, time
for i in range(3):
    try:
        o = json.load(urllib.request.urlopen("http://127.0.0.1:8080/info", timeout=5))
        print("  frames=%s fps=%.1f PL=%.1fms npu=%.2fms cand=%s ntrk=%s stable=%s"
              % (o.get("frames"), o.get("fps", 0), o.get("pl_ms", 0),
                 o.get("npu_ms", 0), o.get("ncand"), o.get("ntrk", "MISSING"),
                 o.get("stable")))
        if "ntrk" not in o:
            print("  [!] ntrk 缺失 —— 说明跑的还是旧版，检查上传")
    except Exception as e:
        print("  [x] /info 失败:", str(e)[:80])
    time.sleep(2)
EOF
'@
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($script3))
& ssh -o ConnectTimeout=8 root@$BOARD "echo '$b64' | base64 -d | bash" 2>&1 | ForEach-Object { Write-Host ("  " + $_) }

Write-Host ""
Write-Host "=== 完成 ===" -ForegroundColor Green
Write-Host "  网页 http://$BOARD:8080/  画面应看到：框上有 #编号、框后有运动轨迹线、HUD 多出 trk 计数"
Write-Host "  回滚：ssh root@$BOARD `"cp /root/ip2/cam3d_pipe.py.bak.$stamp /root/ip2/cam3d_pipe.py && /etc/init.d/ip2d3 restart`""
