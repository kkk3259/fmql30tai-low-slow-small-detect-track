# results/ —— 实测数据表

本目录只保留**数据**（csv / jsonl）与**评测曲线**（png）。
原始的演示视频（14 个 mp4，31.6 MB）已移出版本库——提交的演示视频是单独文件，
这些是中间产物且可由脚本重新生成。

## 数据表（csv）

| 文件 | 内容 |
|---|---|
| `board_full.csv` / `board_bird_full.csv` | 板上逐帧检测结果（真实视频 630 帧）|
| `app_demo.csv` | 应用演示的逐帧记录 |
| `detect_v1.csv` | 软件基线 v1 检测结果 |
| `baseline_synth.csv` | 软件基线在合成序列上的结果 |
| `ablation_gauss.csv` | 高斯核消融实验 |
| `multires_compare.csv` | 多分辨率对比 |
| `nothophat.csv` | 不用 Top-Hat 的对照 |

## 事件流（jsonl）

`app_alerts.jsonl`、`board_full.jsonl`、`board_bird_full.jsonl` —— 逐条告警记录。

## 评测曲线（png）

`sweep_pd_curve.png`（检出率 vs 目标尺寸）、`v3_temporal_compare.png`（时域增强对比）。

## 复现

```bash
python3 ps/eval_testset.py        # 重新生成检测评测
python3 tools/plot_sweep.py       # 重新绘制曲线
```
