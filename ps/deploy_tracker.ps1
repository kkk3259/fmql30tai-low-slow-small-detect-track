# deploy_tracker.ps1 —— 把带航迹跟踪的 cam3d_pipe.py 部署到板子
#
# 前置：板子已加载三域位流（ours3d_s5.bin），且 169.254.67.100 可 ping
# 用法：powershell -ExecutionPolicy Bypass -File ps\deploy_tracker.ps1
#
# 流程：ping 检查 -> 上传 cam3d_pipe.py + 远程脚本 -> ssh 执行远程脚本
#       （备份、语法校验、重启服务、验证 /info 全在远程 .sh 里做，本脚本不写 here-string）

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$BOARD = "169.254.67.100"
$REPO = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$LOCAL_PIPE = Join-Path $REPO "ps\cam3d_pipe.py"
$LOCAL_SH = Join-Path $REPO "ps\deploy_tracker_remote.sh"

$SSH_OPT = @("-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no")
$SCP_OPT = @("-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=no")

Write-Host "=== 0. 本地文件检查 ===" -ForegroundColor Cyan
foreach ($f in @($LOCAL_PIPE, $LOCAL_SH)) {
    if (-not (Test-Path $f)) {
        Write-Host ("  [x] 缺少本地文件: " + $f) -ForegroundColor Red
        exit 1
    }
    $n = (Get-Content $f).Count
    $b = (Get-Item $f).Length
    Write-Host ("  [ok] " + (Split-Path -Leaf $f) + "  ($n 行 / $b B)")
}

Write-Host ""
Write-Host "=== 1. 检查板子 ===" -ForegroundColor Cyan
if (-not (Test-Connection -ComputerName $BOARD -Count 2 -Quiet -ErrorAction SilentlyContinue)) {
    Write-Host ("  [x] " + $BOARD + " ping 不通") -ForegroundColor Red
    Write-Host "      可能原因：P 在跑实验 / 板子挂了 / 网线松"
    Write-Host ("      先确认：ssh root@" + $BOARD + " 'cat /sys/class/fpga_manager/fpga0/state'")
    exit 1
}
Write-Host "  [ok] ping 通"

Write-Host ""
Write-Host "=== 2. 上传 ===" -ForegroundColor Cyan
$dst1 = "root@" + $BOARD + ":/root/ip2/cam3d_pipe.py"
$dst2 = "root@" + $BOARD + ":/tmp/deploy_tracker_remote.sh"
Write-Host "  -> cam3d_pipe.py"
& scp @SCP_OPT $LOCAL_PIPE $dst1 2>&1 | ForEach-Object { Write-Host ("     " + $_) }
Write-Host "  -> deploy_tracker_remote.sh"
& scp @SCP_OPT $LOCAL_SH $dst2 2>&1 | ForEach-Object { Write-Host ("     " + $_) }

Write-Host ""
Write-Host "  转换远程脚本为 LF（板子 bash 不接受 CRLF）" -ForegroundColor Cyan
$sshTarget = "root@" + $BOARD
& ssh @SSH_OPT $sshTarget "sed -i 's/\r$//' /tmp/deploy_tracker_remote.sh; wc -l < /tmp/deploy_tracker_remote.sh" 2>&1 |
    ForEach-Object { Write-Host ("     " + $_) }

Write-Host ""
Write-Host "=== 3. 远程执行（备份 / 校验 / 重启 / 验证）===" -ForegroundColor Cyan
& ssh @SSH_OPT $sshTarget "bash /tmp/deploy_tracker_remote.sh" 2>&1 | ForEach-Object { Write-Host $_ }

Write-Host ""
Write-Host "=== 完成 ===" -ForegroundColor Green
Write-Host ("  网页 http://" + $BOARD + ":8080/")
Write-Host "  预期：框上出现 #编号、框后有运动轨迹线、HUD 多出 trk 计数"
Write-Host ("  若异常：ssh root@" + $BOARD + " 'ls -t /root/ip2/cam3d_pipe.py.bak.* | head -1' 找到备份后 cp 回去并 restart")
