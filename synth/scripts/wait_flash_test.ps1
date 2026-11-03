# 等 ours3d_s4.bit 出流 → 转 bin → 烧板 → 跑竖线图两帧测试
$ErrorActionPreference = "Continue"
$bit = Join-Path $PSScriptRoot "..\..\ours3d_s4.bit"   # 按实际构建产物替换
$bin = Join-Path $PSScriptRoot "ours3d_s4.bin"
$py  = "python.exe"
$scp = "scp.exe"
$ssh = "ssh.exe"
$key = $env:BOARD_KEY
$log = Join-Path $PSScriptRoot "s4_test.txt"

function Say($m) { $t = (Get-Date).ToString("HH:mm:ss"); "$t  $m" | Tee-Object -FilePath $log -Append }

Say "等待位流出流..."
$deadline = (Get-Date).AddMinutes(120)
while ((Get-Date) -lt $deadline) {
    if (Test-Path $bit) {
        $f = Get-Item $bit
        if ($f.Length -gt 5MB) { Say ("位流就绪 {0:N0} B {1}" -f $f.Length, $f.LastWriteTime.ToString("HH:mm:ss")); break }
    }
    Start-Sleep -Seconds 30
}
if (-not (Test-Path $bit)) { Say "超时未出流"; exit 1 }

Say "转 bin..."
& $py "D:\firstharness\repo\tools\mk_bin.py" $bit $bin 2>&1 | Select-Object -Last 2 | ForEach-Object { Say "  $_" }
if (-not (Test-Path $bin)) { Say "转 bin 失败"; exit 1 }

Say "上传到板子..."
& $scp -i $key -o StrictHostKeyChecking=no $bin "root@169.254.67.100:/lib/firmware/ours3d_s4.bin" 2>&1 | Out-Null

Say "烧板..."
& $ssh -i $key -o StrictHostKeyChecking=no root@169.254.67.100 "pkill -9 -f 'cam_pipe[.]py'; sleep 3; echo ours3d_s4.bin > /sys/class/fpga_manager/fpga0/firmware; sleep 3; cat /sys/class/fpga_manager/fpga0/state" 2>&1 | Where-Object { $_ -match "operating|error|denied" } | ForEach-Object { Say "  state: $_" }

Start-Sleep -Seconds 3
$up = Test-Connection -ComputerName 169.254.67.100 -Count 1 -Quiet -ErrorAction SilentlyContinue
Say ("板子 ping = {0}" -f $up)
if (-not $up) { Say "板子失联，停止"; exit 1 }

Say "跑竖线图测试（连跑 3 次，看是否帧帧启动）..."
& $ssh -i $key -o StrictHostKeyChecking=no root@169.254.67.100 "cd /root/ip2 && timeout 200 python3 _vl.py 2>&1 | tail -12" 2>&1 |
    Where-Object { $_ -notmatch "WARNING|post-quantum|store now|openssh|CategoryInfo|FullyQualified|At line|^\s*\+" } |
    ForEach-Object { Say "  $_" }

Say "完成"
