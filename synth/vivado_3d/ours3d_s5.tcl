# 涓夊煙锛堝惈鍍忕礌鎹曡幏锛夐噸缂?set ::env(JFM_PATH) D:/firstharness/JFM_Kits
set L [open D:/firstharness/synth/vivado/ours3d_s5_result.txt w]
proc LOG {m} { global L; puts $L $m; flush $L; puts $m }
set D D:/firstharness/dl/senior_demo/fpai_demo_src_vivado
create_project -force ours3d_s5 D:/firstharness/work/ours3d_s5 -part xc7z030ffg676-2
source D:/firstharness/JFM_Kits/ip_patch/run.tcl
catch {add_hook_tcl_to_prj}
catch {replace_7z030ai_file}
LOG "AIFILE_OK"
read_edif $D/rtl/ps_ai_wrap_demo.edf
read_verilog $D/rtl/ps_ai_wrap_demo.v
set RTL [list D:/firstharness/work/ours3d/ai7030_ours_top.v D:/firstharness/repo/pl/rtl/ip2_user_op.v D:/firstharness/repo/pl/rtl/ip2_axi_top.v D:/firstharness/repo/pl/rtl/ip2_top_stream.v D:/firstharness/repo/pl/rtl/ip2_axi_master_rd.v D:/firstharness/repo/pl/rtl/ip2_axi_master_wr.v D:/firstharness/repo/pl/rtl/candidate_extract_stream.v D:/firstharness/repo/pl/rtl/cfar_threshold_stream.v D:/firstharness/repo/pl/rtl/tophat_5x5_stream.v D:/firstharness/repo/pl/rtl/win5.v D:/firstharness/repo/pl/rtl/minmax_tree.v D:/firstharness/repo/pl/rtl/ip2_pix_fifo.v]
foreach f $RTL { read_verilog $f }
LOG "READ_OK"
read_xdc $D/constrs_1/ai7030.xdc
read_xdc $D/constrs_1/impl_constraints.xdc
LOG "XDC_OK"
synth_design -top ai7030_ours_top -part xc7z030ffg676-2 -flatten_hierarchy rebuilt
LOG "SYNTH_OK"
opt_design
LOG "OPT_OK"
place_design -directive Explore
LOG "PLACE_OK"
route_design -directive Explore
LOG "ROUTE_OK"
set wns [get_property SLACK [get_timing_paths -delay_type max]]
LOG "WNS = $wns"
write_bitstream -force D:/firstharness/work/ours3d_s5/ours3d_s5.bit
LOG "BIT_OK"
close $L
exit 0