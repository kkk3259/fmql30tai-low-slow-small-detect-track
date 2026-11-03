# tools/ —— 数据生成、评测与工具脚本

29 个文件，按用途分五类。

## 数据生成

| 文件 | 作用 |
|---|---|
| `gen_testset.py` | 生成合成测试序列（目标尺寸 × 对比度网格扫描）|
| `gen_richset.py` | 生成场景更丰富的序列（背景杂波、多目标）|
| `gen_skyset.py` | 生成天空背景序列 |
| `make_lowslow_seq.py` | 生成低小慢目标专用序列 |
| `gen_user_test_frame.py` | 生成单帧测试图（用于板上定位问题）|
| `dataset2seq.py` | 把图像数据集转成视频序列 |

## 真值标注与评测

| 文件 | 作用 |
|---|---|
| `mark_gt.py` | 真值标注（生成 gt csv）|
| `plot_sweep.py` | 参数扫描曲线绘制 |
| `sweep_synth.py` | 合成序列的参数扫描 |
| `check_budget.py` | 资源预算核算（LUT/FF/BRAM 估算）|
| `diag_signal.py` | 目标处信噪比诊断 |

## 基准测试（bench_*.py，6 个）

`bench_cfar_param_scan` / `bench_cfar_recall` / `bench_cfar_tradeoff` /
`bench_detect_decomp` / `bench_roi_size` / `bench_topn_recall` / `bench_track_falsealarm`

分别测：CFAR 参数扫描、召回率、权衡曲线、检测环节拆解、ROI 尺寸、候选数上限、跟踪虚警。

## 文档与配图工具

| 文件 | 作用 |
|---|---|
| `md2docx.py` | Markdown → Word 转换（支持标题/粗体/表格/列表/引用）|
| `prep_photo.py` | 手机照片 → 报告规格（旋转、裁剪、亮度拉伸）|
| `make_poster.py` | 海报生成（A2）|
| `make_enclosure.py` | 外壳切割图生成 |

## 位流与板端

| 文件 | 作用 |
|---|---|
| `mk_bin.py` / `mk_swap_bin.py` | 位流转换：`.bit` → 无头 `.bin` + 32 位字字节交换 |
| `verify_ip1.py` | IP1 预处理模块的逐像素比对验证 |
| `probe_ai_mate.py` | AI_Mate 网表探测（135 个顶层端口方向判读）|
| `analyze_kcmp.py` | 二次型均值比较分析 |
| `board_check.sh` | 板端状态检查 |
| `switch_pl.sh` | 位流切换（含 pkill 顺序）|
