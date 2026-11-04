# =============================================================================
# build_bd.tcl —— 在 Vivado 里搭「PS7 + 我们的 IP2 加速器」的 Block Design
#
# 设计目标（对应 docs/14-PS-PL接口约定.md v0.2）：
#     PS (A53/Linux)  --M_AXI_GP0-->  AXI Interconnect  -->  IP2 的 S_AXI（寄存器）
#     PS              <--S_AXI_HP0--  AXI Interconnect  <--  IP2 的 M_AXI（读写 DDR）
#     两边同一时钟 FCLK_CLK0 = 50 MHz（Vivado 里同一个 BD 时钟，不需要跨域 FIFO）
#
# 用法（Windows PowerShell）：
#   cd <工程根>/pl/tools
#   & "<Vivado>/bin/vivado.bat" -mode batch -source build_bd.tcl -nojournal
#   （也可以先开 Vivado GUI，在 Tcl Console 里 `cd <工程根>/pl/tools` 再 `source build_bd.tcl`）
#
# 产出：
#   <工程根>/build/ip2_ps2/ip2_ps.runs/impl_1/*_wrapper.bit  ← 位流
#   <工程根>/build/ip2_ps2/ip2_ps.sdk/…_wrapper.hdf         ← 给 SDK 打 BOOT.bin
#   （2026-10-28：工程目录从 ip2_ps 改成 ip2_ps2 —— 旧目录的 runs 被进程锁住删不掉）
#
# 注意：
#   1. 我们的 RTL 是「同步复位 + 纯时钟域」，Vivado 能推断 RAM（2026-10-26 改过写块）。
#   2. 如果 apply_bd_automation 因为接口属性没识别而报错，看 docs/19 的"手工连法"。
#   3. 器件必须 xc7z030ffg676-2（FMQL30TAI676H 的对标型号）。
# =============================================================================

# 以脚本所在目录（pl/tools）为基准推导工程根，换机器不用改路径
set SCRIPT_DIR [file normalize [file dirname [info script]]]
set ROOT       [file normalize [file join $SCRIPT_DIR ".." ".."]]
set RTL       [file normalize [file join $ROOT "pl" "rtl"]]
set PRJ       [file normalize [file join $ROOT "build" "ip2_ps2"]]
set PS7_CFG   [file normalize [file join $SCRIPT_DIR "ps7_config.tcl"]]
set PART      "xc7z030ffg676-2"
set TOP_BD    "ip2_bd"

puts "\[build_bd\] ===== 1. 创建工程 ====="
# 安全保护：如果当前 Vivado 里已经打开着工程（比如上一次跑失败后没关），
# 必须先关掉，否则 create_project -force 不能替换内存里的那份，
# 后面 create_bd_design ip2_bd 会撞名报 ERROR: [BD 5-137] A design with
# the name ip2_bd already exists.（实测踩过）
if {[llength [current_project -quiet]] > 0} {
    puts "\[build_bd\] 检测到已打开的工程：[current_project]，先关闭"
    close_project -quiet
}
# 若内存里还残留同名 BD，也一并清掉（关工程后一般不会再有，兜底）
if {[llength [get_bd_designs -quiet $TOP_BD]] > 0} {
    puts "\[build_bd\] 发现内存里残留 BD $TOP_BD，先删除"
    catch { delete_bd_objs [get_bd_designs $TOP_BD] }
}

# 工程目录先物理删除：create_project -force 对"已存在的工程目录"会失败，
# 且 -quiet 会把真实错误吞掉，只报 [Coretcl 2-88] No projects are currently open.
# 实测踩过两次。关掉工程后删除目录再建，最稳。
proc _rmdir {p} {
    if {[file exists $p]} {
        puts "\[build_bd\] 删除旧工程目录 $p"
        if {[catch { file delete -force $p } e]} {
            puts "\[build_bd\] 删除失败（可能被占用）：$e"
        }
    }
}
_rmdir $PRJ

if {[catch {create_project -force ip2_ps $PRJ -part $PART} e]} {
    # 注意：这里不能用 exit（在 GUI 里 source 时 exit 会把 Vivado 关掉）
    error "\[build_bd\] create_project 失败：$e"
}
set_property target_language Verilog [current_project]
set_property "board_part" "" [current_project]

puts "\[build_bd\] ===== 2. 加入 RTL 源文件 ====="
set rtl_files [list \
    "$RTL/win5.v" \
    "$RTL/tophat_5x5_stream.v" \
    "$RTL/cfar_threshold_stream.v" \
    "$RTL/candidate_extract_stream.v" \
    "$RTL/ip2_top_stream.v" \
    "$RTL/ip2_pix_fifo.v" \
    "$RTL/ip2_axi_master_rd.v" \
    "$RTL/ip2_axi_master_wr.v" \
    "$RTL/ip2_axi_top.v" \
    "$RTL/ip2_axi_bd_wrap.v" \
]
add_files -norecurse -fileset sources_1 $rtl_files
update_compile_order -fileset sources_1

puts "\[build_bd\] ===== 3. 建 Block Design 并放 PS7 ====="
create_bd_design $TOP_BD
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0

puts "\[build_bd\] ===== 4. 套用官方出厂 PS 配置（DDR3/QSPI/SD/UART/ENET/CAN + MIO 全表） ====="
source $PS7_CFG
# 整批应用最快，但任何一个参数非法都会导致整批回滚（Vivado 报
# ERROR [IP_Flow 19-3452] Invalid long/float value ''），所以失败时退回逐条应用。
if {[catch {set_property -dict $ps7_cfg [get_bd_cells processing_system7_0]} err]} {
    puts "\[build_bd\] WARN: 整批应用失败，改逐条应用。原始错误：$err"
    set failed {}
    set n [llength $ps7_cfg]
    for {set i 0} {$i < $n} {incr i 2} {
        set k [lindex $ps7_cfg $i]
        set v [lindex $ps7_cfg $i+1]
        if {[catch {set_property $k $v [get_bd_cells processing_system7_0]} e2]} {
            lappend failed $k
        }
    }
    puts "\[build_bd\] 逐条应用完成：失败 [llength $failed] 条"
    if {[llength $failed] > 0} {
        puts "\[build_bd\] 失败参数（最多显示 20 个）: [lrange $failed 0 19]"
    }
}
puts "\[build_bd\]   校验：M_AXI_GP0 使能 = [get_property CONFIG.PCW_USE_M_AXI_GP0 [get_bd_cells processing_system7_0]]"
puts "\[build_bd\]   校验：S_AXI_HP0 使能 = [get_property CONFIG.PCW_USE_S_AXI_HP0 [get_bd_cells processing_system7_0]]"
puts "\[build_bd\]   校验：FCLK0 频率   = [get_property CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ [get_bd_cells processing_system7_0]] MHz"

# 【关键（2026-10-27 改）：寄存器口走 GP0，不走 GP1】
#   原因：板子上的官方 BOOT.bin 里那个 FSBL，是按官方 AI_Mate 设计生成的，
#         它的 ps7_init 只使能了 M_AXI_GP0 + S_AXI_HP0~3（官方设计就是用 GP0 访 AI_Mate 寄存器）。
#         GP1 从未被使能 => 访问 GP1 窗口（0x8000_0000~0xBFFF_FFFF）必然 SIGBUS（S 已实测）。
#   换用 GP0 的好处：不用重打 BOOT.bin、不用重生 FSBL、不动 SD 卡，
#         只要用 JTAG 把我们的 bit 下载进去，PS 就能访问寄存器。
#   Zynq-7000 PS 主口地址窗口固定：
#     M_AXI_GP0 -> 0x4000_0000 ~ 0x7FFF_FFFF
#     M_AXI_GP1 -> 0x8000_0000 ~ 0xBFFF_FFFF
#   寄存器基址取 0x43C00000（Xilinx 传统位置，避开 AI_Mate 的 0x40000000 段）。
set_property -dict [list \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_USE_M_AXI_GP1 {0} \
    CONFIG.PCW_USE_S_AXI_HP0 {1} \
    CONFIG.PCW_USE_S_AXI_HP1 {0} \
    CONFIG.PCW_USE_S_AXI_HP2 {0} \
    CONFIG.PCW_USE_S_AXI_HP3 {0} \
    CONFIG.PCW_USE_S_AXI_ACP {0} \
] [get_bd_cells processing_system7_0]

puts "\[build_bd\] ===== 5. 把 DDR / FIXED_IO / FCLK 引出成外部端口 ====="
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" apply_board_preset "0" Master "Disable" Slave "Disable"} \
    [get_bd_cells processing_system7_0]

puts "\[build_bd\] ===== 6. 放入我们的 IP2 加速器 ====="
create_bd_cell -type module -reference ip2_axi_bd_wrap ip2_0

puts "\[build_bd\] ===== 7. 自动接 AXI：GP0 -> S_AXI（0x43C00000 寄存器）、M_AXI -> HP0（DDR 带宽） ====="
# 7a. 寄存器口：PS 主 GP0 -> 我们从
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Master "/processing_system7_0/M_AXI_GP0" Clk "Auto" } \
    [get_bd_intf_pins ip2_0/S_AXI]
# 7b. 数据口：我们主 -> PS 从（HP0 是 64 bit 高性能口，正好配我们 64 bit 读突发）
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Master "/ip2_0/M_AXI" Clk "Auto" } \
    [get_bd_intf_pins processing_system7_0/S_AXI_HP0]

puts "\[build_bd\] ===== 8. 时钟与复位 ====="
# apply_bd_automation 一般已经建了 rst_ps7_50M（proc_sys_reset）和 FCLK 连接，
# 这里做兜底：如果 clk / rst_n 还悬空，就手动补上。
if {[get_bd_nets -quiet -of_objects [get_bd_pins ip2_0/clk]] eq ""} {
    connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins ip2_0/clk]
}
if {[get_bd_nets -quiet -of_objects [get_bd_pins ip2_0/rst_n]] eq ""} {
    set rst_cell [get_bd_cells -quiet rst_ps7_50M]
    if {$rst_cell eq ""} {
        create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_ps7_50M
        connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins rst_ps7_50M/slowest_sync_clk]
        connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins rst_ps7_50M/ext_reset_in]
    }
    connect_bd_net [get_bd_pins rst_ps7_50M/peripheral_aresetn] [get_bd_pins ip2_0/rst_n]
}

puts "\[build_bd\] ===== 9. LED 引脚引出（J1 = led[0]，其余三个可留空） ====="
create_bd_port -dir O -from 3 -to 0 led
connect_bd_net [get_bd_ports led] [get_bd_pins ip2_0/led]

puts "\[build_bd\] ===== 10. 地址分配：寄存器基址 = 0x43C00000（GP0 段内） ====="
# 说明（2026-10-26 踩坑）：不能用 `get_bd_addr_segs -of_objects [get_bd_cells ip2_0]` 去找寄存器段——
# slave 侧 cell 本身不拥有地址段，段挂在**主口（PS）的地址空间**里，那样遍历是空集，offset 静默不生效。
# 正确做法：从 PS 的地址空间里按名字匹配 ip2_0。
assign_bd_address
set REG_BASE_ADDR 0x43C00000
# 注意：get_bd_addr_segs 没有 -address_space 选项（那是 get_bd_addr_spaces），
# 要用 -of_objects [get_bd_addr_spaces <主口>] 才能拿到该地址空间下的段列表。
set segs [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces processing_system7_0/Data]]
set hit 0
foreach s $segs {
    if {[string match "*ip2_0*" $s]} {
        set_property offset $REG_BASE_ADDR $s
        incr hit
        puts "\[build_bd\]   寄存器段: $s -> offset [get_property offset $s]  range [get_property range $s]"
    }
}
if {$hit == 0} { error "地址段没找到：PS/Data 地址空间里没有 *ip2_0* 的段，检查第 7 步 GP0 连接" }
puts "\[build_bd\]   寄存器段命中 $hit 个，应当为 1"

puts "\[build_bd\] ===== 11. 校验并存盘 ====="
validate_bd_design
save_bd_design

puts "\[build_bd\] ===== 12. 生成 HDL 顶层 wrapper ====="
set bd_file [get_files $TOP_BD.bd]
make_wrapper -files $bd_file -top
set wrapper [glob -nocomplain "$PRJ/ip2_ps.srcs/sources_1/bd/$TOP_BD/hdl/${TOP_BD}_wrapper.v"]
if {$wrapper eq ""} { error "没找到 BD wrapper，请检查 make_wrapper 输出" }
add_files -norecurse -fileset sources_1 $wrapper
set_property top ${TOP_BD}_wrapper [current_fileset]
update_compile_order -fileset sources_1

puts "\[build_bd\] ===== 13. 约束：LED[3:0] = J1/M6/H7/J8（LVCMOS15） ====="
set xdc "$ROOT/synth/vivado/ip2_ps_pins.xdc"
set fh [open $xdc w]
puts $fh "# IP2 + PS BD 的引脚约束（时钟/复位由 BD 内部提供，不需要 create_clock）"
puts $fh "# PL 侧 4 个 LED：led[0]=J1、led[1]=M6、led[2]=H7、led[3]=J8"
puts $fh "# 出处：官方 fpai_demo_fpga/constrs_1/impl_constraints.xdc（BANK13，1.5V → LVCMOS15）"
puts $fh "# 注意：4 个 LED 必须全部约束，否则 write_bitstream 的 DRC 会报"
puts $fh "#       NSTD-1（无 IOSTANDARD）/ UCIO-1（无 LOC）而拒绝出位流。"
puts $fh "set_property PACKAGE_PIN J1 \[get_ports {led\[0\]}\]"
puts $fh "set_property IOSTANDARD LVCMOS15 \[get_ports {led\[0\]}\]"
puts $fh "set_property PACKAGE_PIN M6 \[get_ports {led\[1\]}\]"
puts $fh "set_property IOSTANDARD LVCMOS15 \[get_ports {led\[1\]}\]"
puts $fh "set_property PACKAGE_PIN H7 \[get_ports {led\[2\]}\]"
puts $fh "set_property IOSTANDARD LVCMOS15 \[get_ports {led\[2\]}\]"
puts $fh "set_property PACKAGE_PIN J8 \[get_ports {led\[3\]}\]"
puts $fh "set_property IOSTANDARD LVCMOS15 \[get_ports {led\[3\]}\]"
close $fh
add_files -norecurse -fileset constrs_1 $xdc

puts "\[build_bd\] ===== 14. 综合 + 实现 + 位流（约 20~40 分钟） ====="
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
    error "impl_1 没跑完，看 $PRJ/ip2_ps.runs/impl_1/runme.log"
}

puts "\[build_bd\] ===== 15. 导出硬件（SDK 打 BOOT.bin 要用） ====="
write_hwdef -force [file normalize [file join $ROOT "build" "ip2_bd.hwdef"]]
open_run impl_1
report_utilization      -file [file normalize [file join $ROOT "build" "utilization.rpt"]]
report_timing_summary   -file [file normalize [file join $ROOT "build" "timing.rpt"]] -max_paths 20
puts "\[build_bd\] ===== 完成 ====="
puts "\[build_bd\] 位流: $PRJ/ip2_ps.runs/impl_1/${TOP_BD}_wrapper.bit"
puts "\[build_bd\] 资源: $ROOT/build/utilization.rpt"
puts "\[build_bd\] 时序: $ROOT/build/timing.rpt"
