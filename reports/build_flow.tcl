set L [open D:/firstharness/synth/vivado/ours3d_bram_result.txt w]
proc LOG {m} { global L; puts $L $m; flush $L; puts $m }
set ::env(JFM_PATH) D:/firstharness/JFM_Kits
create_project -force ours3dbram D:/firstharness/work/ours3d_bram_prj -part xc7z030ffg676-2
source D:/firstharness/JFM_Kits/ip_patch/run.tcl
catch {add_hook_tcl_to_prj}
catch {replace_7z030ai_file}
set D   D:/firstharness/dl/senior_demo/fpai_demo_src_vivado
set RTL D:/firstharness/repo/pl/rtl
set_param general.maxThreads 6
read_edif    $D/rtl/ps_ai_wrap_demo.edf
read_verilog $D/rtl/ps_ai_wrap_demo.v
read_verilog D:/firstharness/work/ours3d/ai7030_ours_top_se5.v
foreach f [list ip2_user_op ip2_axi_top ip2_top_stream tophat_5x5_stream win5 minmax_tree cfar_threshold_stream candidate_extract_stream ip2_pix_fifo ip2_axi_master_rd ip2_axi_master_wr] {
    read_verilog $RTL/$f.v
}
read_xdc $D/constrs_1/ai7030.xdc
read_xdc $D/constrs_1/impl_constraints.xdc
LOG "READ_OK"
if {[catch {synth_design -top ai7030_ours_top_se5 -part xc7z030ffg676-2} e]} { LOG "SYNTH_FAIL :: $e"; close $L; exit 1 }
LOG "SYNTH_OK"
report_utilization -file D:/firstharness/synth/vivado/ours3d_bram_util.rpt
if {[catch {opt_design} e]} { LOG "OPT_FAIL :: $e"; close $L; exit 1 }
LOG "OPT_OK"
if {[catch {place_design -directive Explore} e]} { LOG "PLACE_FAIL :: $e"; close $L; exit 1 }
LOG "PLACE_OK"
if {[catch {route_design} e]} { LOG "ROUTE_FAIL :: $e"; close $L; exit 1 }
LOG "ROUTE_OK"
report_timing_summary -file D:/firstharness/synth/vivado/ours3d_bram_timing.rpt
if {[catch {write_bitstream -force D:/firstharness/work/ours3d_bram/ours3d_bram.bit} e]} { LOG "BIT_FAIL :: $e"; close $L; exit 1 }
LOG "BIT_OK"
LOG "=== END ==="
close $L
exit 0
