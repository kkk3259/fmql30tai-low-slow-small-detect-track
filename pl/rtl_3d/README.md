# 三域（PS7 + AI_Mate NPU + IP2 检测器）工程归档

> 本目录是副本，仅供版本留档与可复现性。
> 编译时以工作目录下的原件为准，原件路径见下表；请勿修改本目录内的文件来"修 bug"，
> 否则会和实际编译用的版本分叉。

## 原件位置（编译真正读取的）

| 本目录文件 | 原件路径 | 作用 |
|---|---|---|
| `pl/rtl_3d/ai7030_ours_top.v` | 原工程路径 `work/ours3d/ai7030_ours_top.v` | 三域顶层：例化 `ps_ai_wrap_demo`（平台 EDIF）+ `ip2_user_op`（自研检测器适配层） |
| `synth/vivado_3d/ours3d_s5.tcl` | `synth\vivado\\ours3d_s5.tcl` | 三域综合+实现脚本（read_edif + 桩 + RTL + XDC + synth/opt/place/route/bitstream） |
| `synth/vivado_3d/ours3d_fifo.tcl` | `synth\vivado\\ours3d_fifo.tcl` | 上一版（16 行 FIFO + AR 队列），已验证 AR=RV=3609 |
| `synth/scripts/wait_s5_flash2.ps1` | `<工程根>\dl\wait_s5_flash2.ps1` | 等位流→转 bin→烧板→探活→跑 seq_test 的流水线 |
| `synth/scripts/wait_flash_test.ps1` | `<工程根>\dl\wait_flash_test.ps1` | 同上，早期版本 |

## 三域顶层关键参数（当前）

```verilog
ip2_user_op #( .W(640), .H(360), .SE(5), .MAX_CAND(8) )
```

 `SE(5)` 是历史遗留：当初 SE=21 时三域 LUT 114% 装不下，为压资源改成 5。
后果是三域里检测窗口只有 2~4 px（独立版 `pl/rtl/ip2_axi_top.v` 默认 `SE=31`，窗口 6~28 px）。
做正式演示前应改成 `SE(31), MAX_CAND(16)` 重编一版（约 90 分钟）。

## 编译依赖清单（`ours3d_s5.tcl` 里 `set RTL` 那行）

```
work/ours3d/ai7030_ours_top.v
repo/pl/rtl/ip2_user_op.v ← 平台 512 位口 ↔ 检测器 64 位主口的适配层
repo/pl/rtl/ip2_axi_top.v
repo/pl/rtl/ip2_top_stream.v
repo/pl/rtl/ip2_axi_master_rd.v
repo/pl/rtl/ip2_axi_master_wr.v ← 候选表写 DDR，cand_bytes=0 已停用（F_WRITE 直接判完成）
repo/pl/rtl/candidate_extract_stream.v
repo/pl/rtl/cfar_threshold_stream.v
repo/pl/rtl/tophat_5x5_stream.v
repo/pl/rtl/win5.v
repo/pl/rtl/minmax_tree.v
repo/pl/rtl/ip2_pix_fifo.v
```

外加：
- `dl/senior_demo/fpai_demo_src_vivado/rtl/ps_ai_wrap_demo.edf`（132 MB，PS7+AI_Mate+MIG+HDMI 平台网表）
- `dl/senior_demo/.../rtl/ps_ai_wrap_demo.v`（80 端口桩，必须读入供 EDIF 填实）
- `dl/senior_demo/.../constrs_1/ai7030.xdc` + `impl_constraints.xdc`
- `JFM_Kits/ip_patch/run.tcl` + `add_hook_tcl_to_prj` + `replace_7z030ai_file`（**必须**，否则 PS7 是黑盒）

## 一键恢复/编译顺序

```tcl
set ::env(JFM_PATH) <JFM_Kits>
source <JFM_Kits>/ip_patch/run.tcl
add_hook_tcl_to_prj ;# 打印 Set BRAM/FIFO -bram_patch_check TRUE!
replace_7z030ai_file ;# 换 zynq.rtd 成 30AI 版，否则 INBB-3
read_edif .../ps_ai_wrap_demo.edf
read_verilog .../ps_ai_wrap_demo.v
read_verilog {上面 RTL 清单}
read_xdc {两个 xdc}
synth_design -top ai7030_ours_top -part xc7z030ffg676-2 -flatten_hierarchy rebuilt
opt_design ; place_design -directive Explore ; route_design -directive Explore
write_bitstream -force -bin_file ...
```

位流转 bin 一律用 `repo/tools/mk_bin.py`（按 `AA995566` 同步字找头，头长 110/111/115 都出现过，不要写死）。
