# flash_bit.ps1 —— 把位流烧进 PL（fpga_manager 自加载，可远程执行）
#
# 用法：
#   powershell -File flash_bit.ps1 -Bin ./synth\vivado\ip2_ps4\ip2_board_se21.bin
#
# 要点（踩过的坑，别改）：
#   1. 必须用 Vivado 的 `write_bitstream -bin_file` 直接生成的**无头 .bin**；
#      拿 .bit 去剥文本头再交换字节的做法在部分构建上会剥错（实测前 16 字节变成 ASCII 垃圾）。
#   2. .bin 必须按 32 位字**字节交换**后才给 fpga_manager（否则报
#      "Invalid bitstream, could not find a sync word"）。交换后前 4 字节应是 FF FF FF FF。
#   3. **重配置前先停掉正在跑的应用**，否则 PS 侧还有未完成的 AXI 事务，PL 一重配就会
#      把 PS 总线挂死（实测：写完 firmware 后板子直接失联，只能按 RST_POR 或断电重启）。
param(
    [Parameter(Mandatory = $true)][string]$Bin,
    [string]$Board = "root@169.254.67.100",
    [switch]$SkipStop
)
$ErrorActionPreference = "Continue"
# 依赖 PATH 中的 ssh / scp / python；板卡私钥路径由环境变量 BOARD_KEY 指定
$ssh = "ssh.exe"
$scp = "scp.exe"
$key = $env:BOARD_KEY
$py = "python.exe"

if (-not (Test-Path $Bin)) { "ERROR: 找不到 $Bin"; exit 1 }
$item = Get-Item $Bin
"位流: $($item.FullName)  $($item.LastWriteTime.ToString('HH:mm:ss'))  $($item.Length) B"

# 1) 字节交换（Vivado 已生成无头 .bin，这里只交换，不剥头）
$swapped = [System.IO.Path]::Combine($item.DirectoryName, ($item.BaseName + "_swap.bin"))
& $py "./tools\mk_swap_bin.py" $Bin $swapped | Out-Null
if (-not (Test-Path $swapped)) { "ERROR: 字节交换失败"; exit 1 }
$head = [System.IO.File]::ReadAllBytes($swapped)[0..3]
$headHex = ($head | ForEach-Object { $_.ToString("X2") }) -join " "
"交换后: $((Get-Item $swapped).Length) B, 前 4 字节 = $headHex"
if ($headHex -ne "FF FF FF FF") {
    "ERROR: 前 4 字节不是 FF FF FF FF —— 这不是无头 .bin，请用 write_bitstream -bin_file 重新生成"
    exit 1
}

# 2) 停应用（避免重配置时挂死 PS）
if (-not $SkipStop) {
    & $ssh -i $key -o StrictHostKeyChecking=no -o ConnectTimeout=10 $Board "pkill -f 'cam_pipe[.]py'; pkill -f 'cam_demo[.]py'; sleep 1; echo STOPPED" 2>&1 |
        Where-Object { $_ -match "STOPPED" }
}

# 3) 上传 + 自加载
& $scp -i $key -o StrictHostKeyChecking=no $swapped "${Board}:/lib/firmware/ip2_bd_wrapper.bin" 2>&1 | Out-Null
"上传完成"
& $ssh -i $key -o StrictHostKeyChecking=no -o ConnectTimeout=10 $Board "md5sum /lib/firmware/ip2_bd_wrapper.bin; sync; echo ip2_bd_wrapper.bin > /sys/class/fpga_manager/fpga0/firmware; sleep 2; cat /sys/class/fpga_manager/fpga0/state" 2>&1 |
    Where-Object { $_ -notmatch "post-quantum|store now|openssh|CategoryInfo|FullyQualified|^\s*\+|^\s*$" }
"=== 烧写流程结束（state 应为 operating）==="
