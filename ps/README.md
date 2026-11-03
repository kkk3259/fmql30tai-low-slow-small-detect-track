# ps/ —— PS 侧应用

本目录是运行在 ARM 核心上的 Python 应用层，负责视频采集、PL/NPU 调度、航迹管理与网页呈现。
共 117 个文件，按用途分 8 类，**加粗的是核心链路的入口脚本**。

---

## 一、核心实时链路（建议先看这 4 个）

| 文件 | 作用 |
|---|---|
| **`cam_pipe.py`** | 独立检测器版实时链路：V4L2 采集 → PL 检测 → 卡尔曼跟踪 → 网页 MJPEG。实测 24.3~28.9 fps（视配置） |
| **`cam3d_pipe.py`** | 三域版实时链路：多一段 NPU 判别。窗口内是 `检测框 #编号 面积 peak 概率`，实测 16.6 fps |
| **`web_console.py`** | 网页控制台：实时视频 + 检测框/航迹/ID 叠加 + 在线调参 + 近 60 帧耗时曲线 + 目标列表 |
| `cam3d_test.py` | 三域链路无界面自测（相机 → PL → NPU），用于排查不依赖网页 |

**两个版本的差别**：`cam_pipe` 只跑 PL，帧率高但没有类别判别；`cam3d_pipe` 多一级 NPU 二分类，
代价是每候选 0.9~1.9 ms，换来「是不是无人机」的概率。两者共用同一套跟踪与推流逻辑。

---

## 二、级联与端到端

| 文件 | 作用 |
|---|---|
| **`cascade.py`** | PL 候选 → 按面积定裁剪边长 → 缩到 128×128 → cls128 判别 → 阈值过滤 |
| **`full_pipeline.py`** | 端到端脚本：视频/摄像头 → PL 找目标 → NPU 判无人机 → 画框输出 mp4 |
| `stream_cascade.py` / `stream_cascade_cls.py` | 级联推流（含网格打包变体，2×2 打包实测 2.90× 加速） |

---

## 三、NPU 相关

| 文件 | 作用 |
|---|---|
| `stream_npu.py` | NPU 全图推理推流（yolov11n，对照用） |
| `npu_video.py` / `npu_video_board.py` | NPU 视频流水线（PC 侧 / 板端） |
| `npu_smoke.py` | NPU 冒烟测试：设备打开、模型加载、一次前向 |
| `npu_cls128.py` / `npu_read.py` / `npu_dump.py` / `npu_host.py` | 输出回读的几种方式探索（正确写法见 `cascade.py`） |
| `npu_err.py` / `npu_memread.py` / `npu_twoarg.py` / `npu_trigger_test.py` | 错误路径与边界测试 |

> 关键教训：`outs[i].read(buf, 0, n)` 是唯一可用的回读方式；官方 `Tensor.dump()` 在 Python 绑定里会报错。
> 若遇到 `MMU isn't enabled`，先确认位流里有没有 AI_Mate，而不是怀疑 Python 版本。

---

## 四、PL 交互与调试

| 文件 | 作用 |
|---|---|
| `pl_link.py` | PL 寄存器读写封装（`/dev/mem` 映射） |
| `pl_cam_demo.py` | PL 检测链路的相机演示 |
| `pl_selftest.py` | PL 自检：版本号、状态字、候选表读取 |
| `detect3d.py` | 三域位流下的单帧检测（寄存器基址 `0x400C0000`），**换位流后先跑这个** |
| `ip2_dbg3d.py` / `dbg_probe3d.py` / `t3d.py` | 三域调试辅助 |

---

## 五、评测与基准

| 文件 | 作用 |
|---|---|
| `eval_testset.py` / `eval_testset2.py` / `eval_testset3d.py` | 在测试集上评召回/虚警（报告数据来源） |
| `eval_vs_ref.py` | 与 OpenCV 参考实现逐像素比对 |
| `size_sweep.py` / `size_sweep_ms.py` | 目标尺寸扫描（产出能力边界曲线） |
| `contrast_test.py` | 对比度扫描 |
| `bench_*.py`（6 个）| 各环节耗时基准（采集/编码/张量复用/主机开销等） |

---

## 六、单元测试

`test_target.py`、`test_flow.py`、`test_tracker.py`、`test_counts.py`、`test_evict.py`、`test_sync.py`、`test_stream.py`

覆盖：目标尺寸与坐标映射、7 环节流程、卡尔曼匹配与航迹生命周期、候选计数、FIFO 逐出、跨域同步、流式接口。

---

## 七、探测与诊断（一次性工具，保留备查）

- **候选表读取**：`read_cand.py`、`cand_read.py`、`cand_legacy.py`、`dump_table.py`、`capdump.py`
- **寄存器**：`reg_read.py`、`reg_dump.py`、`raw_dump.py`、`addr_probe.py`、`addr_scan.py`、`alias_check.py`
- **时序**：`ar_curve.py`（启动后每 1 ms 采 AR/RV/WD）、`trace_feed.py`、`row_sweep.py`、`rows_probe.py`
- **坐标**：`shift_probe.py`、`verify_shift.py`、`center_check.py`、`corners.py`
- **其他**：`la_dump.py`（片上逻辑分析仪）、`still_probe.py`、`which_bit.py`、`analyze_miss.py`、`why_miss.py`

---

## 八、部署与系统

| 文件 | 作用 |
|---|---|
| `deploy_tracker.ps1` + `deploy_tracker_remote.sh` | 一键部署带跟踪的 cam3d_pipe 到板子（含备份、语法校验、自动回滚）|
| `recover_board.sh` | 板子恢复：加载已知可用位流 + 重启服务 |
| `ip2demo.init` / `ip2d3.init` | init.d 服务脚本（独立版 / 三域版）|
| `eth0.static` / `eth0.ifupdown` | 静态 IP 配置 |
| `check_cam.sh` / `sync_test.sh` / `run_mv.sh` / `run_gamma_sweep.sh` | 板端小工具 |
| `ip2_demo.cpp` / `ip2probe.cpp` | 早期 C++ 探测程序 |

---

## 换位流时的纪律（务必遵守）

```bash
pkill -9 -f 'cam_pipe[.]py'; pkill -9 -f 'cam3d_pipe[.]py'   # 先停所有访问 PL 的进程
sleep 3
echo <位流文件名>.bin > /sys/class/fpga_manager/fpga0/firmware
sleep 3
cat /sys/class/fpga_manager/fpga0/state      # 必须是 operating
```

> 若重配 PL 时还有进程持有 `/dev/mem` 映射或未完成的 AXI 事务，会挂死 PS 总线，只能断电重启。
> `pkill` 的模式要带方括号（如 `cam_[p]ipe`），否则会匹配到自己这条 ssh 命令。
