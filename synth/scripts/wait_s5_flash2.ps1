$ErrorActionPreference = "Continue"
$py  = "D:\firstharness\venv\Scripts\python.exe"
$k   = "D:\firstharness\dl\board_key"
$scp = "C:\Users\xujia\Git\usr\bin\scp.exe"
$ssh = "C:\Users\xujia\Git\usr\bin\ssh.exe"
$B   = "root@169.254.67.100"
$bit = "D:\firstharness\work\ours3d_s5\ours3d_s5.bit"
$bin = "D:\firstharness\dl\ours3d_s5.bin"
$out = "D:\firstharness\dl\s5_report.txt"
$log = New-Object System.Collections.ArrayList

function L($m) {
    $t = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $m
    Write-Output $t
    [void]$log.Add($t)
}

L "wait for bitstream"
$deadline = (Get-Date).AddMinutes(150)
while ((Get-Date) -lt $deadline) {
    if (Test-Path $bit) {
        if (((Get-Date) - (Get-Item $bit).LastWriteTime).TotalSeconds -gt 20) { break }
    }
    Start-Sleep -Seconds 30
}
if (-not (Test-Path $bit)) { L "TIMEOUT no bit"; $log | Set-Content $out; exit 1 }
L ("bit {0:N0} B {1}" -f (Get-Item $bit).Length, (Get-Item $bit).LastWriteTime.ToString("HH:mm:ss"))

& $py "D:\firstharness\repo\tools\mk_bin.py" $bit $bin 2>&1 | ForEach-Object { L ("mk_bin " + $_) }
if (-not (Test-Path $bin)) { L "mk_bin FAILED"; $log | Set-Content $out; exit 1 }

& $scp -i $k -o StrictHostKeyChecking=no $bin "${B}:/lib/firmware/" 2>&1 | Out-Null
& $scp -i $k -o StrictHostKeyChecking=no "D:\firstharness\repo\ps\probe_ver.py" "${B}:/root/ip2/" 2>&1 | Out-Null
L "scp done"

$r = & $ssh -i $k -o StrictHostKeyChecking=no $B "pkill -9 -f 'cam_pipe[.]py'; pkill -9 -f 'cam3d_[t]est'; sleep 3; echo ours3d_s5.bin > /sys/class/fpga_manager/fpga0/firmware; sleep 3; cat /sys/class/fpga_manager/fpga0/state" 2>&1
foreach ($x in $r) { if ($x -match "operating|rror|ail|enied") { L ("flash " + $x) } }

$r = & $ssh -i $k -o StrictHostKeyChecking=no $B "cd /root/ip2; timeout 25 python3 probe_ver.py" 2>&1
$ok = $false
foreach ($x in $r) { L ("probe " + $x); if ($x -match "VER 0x00010000") { $ok = $true } }
if (-not $ok) { L "PROBE_FAIL board may be hung, stop"; $log | Set-Content $out; exit 2 }
L "PROBE_OK"

$r = & $ssh -i $k -o StrictHostKeyChecking=no $B "cd /root/ip2; timeout 90 python3 seq_test.py /root/ip2/vs_300.png 4 2>&1 | grep -aE 'FRAME|#[45]'" 2>&1
foreach ($x in $r) { L ("seq4 " + $x) }

$r = & $ssh -i $k -o StrictHostKeyChecking=no $B "cd /root/ip2; timeout 90 python3 seq_test.py /root/ip2/vs_100.png 2 2>&1 | grep -aE 'FRAME|#[45]'" 2>&1
foreach ($x in $r) { L ("seq100 " + $x) }

$r = & $ssh -i $k -o StrictHostKeyChecking=no $B "cd /root/ip2; timeout 150 python3 cam3d_test.py --n 6 --npu 0 2>&1 | tail -10" 2>&1
foreach ($x in $r) { L ("chain " + $x) }

$log | Set-Content $out
L "ALL_DONE"
