# report/ —— 作品报告的生成链（可复现）

本目录存放作品报告与各文档的生成脚本，目的是让报告的产出过程**可复现**，
满足赛题要求中的"提交可复现的工程文件"。

## 目录内容

| 文件 | 作用 |
|---|---|
| `fill_report.py` | **主体脚本**：读取官方模板，把各章节内容与表格填充进 `word/document.xml`，输出 `out_report.docx` |
| `insert_figs.py` | **插图脚本**：把 `figs/` 下的图片按锚点插入报告，输出 `out_report_img.docx` |
| `md2docx.ps1` | **Markdown → Word** 转换工具（把 `docs/*.md` 转成 `.docx`）|
| `template_技术文档（报告）.docx` | 官方报告模板（**输入**，来自赛题文件）|
| `figs/` | 报告插图源文件（8 张 PNG）|

## 生成流程（两步）

```powershell
# 0) 准备：把本机路径按你的环境改好（见下方"路径说明"）
$py = "D:\lowslow\venv\Scripts\python.exe" # 换成你自己的虚拟环境

# 1) 填充内容（产出 out_report.docx）
& $py report\fill_report.py

# 2) 插入插图（产出 out_report_img.docx）—— 这就是最终报告
& $py report\insert_figs.py
```

**产物**：`out_report_img.docx` → 复制到 `docs/08-作品报告（完整版）.docx`

## 各 Markdown 文档 → Word

```powershell
# md2docx.ps1 是一个脚本块，需要在变量 $Docs 指向待转换目录后执行
$Docs = "D:\你的工作目录"
Invoke-Expression ([IO.File]::ReadAllText('report\md2docx.ps1', [Text.Encoding]::UTF8))
```
> 调用方请用 `$workDir` 之类的变量名，不要用 `$tmp` —— `md2docx.ps1` 内部会覆盖同名变量。

## 路径说明（重要）

两个 Python 脚本里的路径是**本机绝对路径**，换机器时需要修改文件头部的常量：

| 脚本 | 常量 | 含义 |
|---|---|---|
| `fill_report.py` | `TPL` | 报告模板路径 |
| `fill_report.py` | `OUT` | 中间产物输出路径 |
| `insert_figs.py` | `ROOT` / `IMG_DIR` | 插图目录 |

> 这是历史写法（脚本最初为单机使用），**不影响报告内容本身** —— 报告产物 `docs/08-作品报告（完整版）.docx` 已在仓库中，可直接使用。

## 报告结构（11 个表格 / 8 张插图）

> 2026-10-23 实测核对：产物 `docs/08-作品报告（完整版）.docx` 为非空段落 174 段、**表格 11 个**、嵌入图片 10 张（8 张插图 + 2 张模板自带）。
>
> 修改内容请改 `fill_report.py` 再重跑，不要手改产物 docx —— 否则下次重跑会被覆盖。插图仍占位 4 处（图 3/4/7/8 实物图，待拍摄）。

内容按赛题模板的章节组织，其中与实测数据相关的关键章节：

| 章节 | 内容 | 数据来源 |
|---|---|---|
| 3.3（1)~(9) | 真实数据验证、结果解读、时域增强收益、系统集成链路表现、候选数上限优化 | `docs/weekly/周报-W40.md` |
| 表格 | 真实场景 vs 合成序列对比、参数尝试、候选数上限对照 | `results/*.csv` |
| 插图 | 系统框图、硬件连接、软件流程、PL 模块框图、检测跟踪效果、检出率曲线、仿真波形、技术路线 | `report/figs/` |

## 保持一致的注意事项

1. 不要手改产物 docx —— 所有内容改动应回到 `fill_report.py`，然后重新生成；
2. **插图替换**：换 `figs/` 里的图片后重跑 `insert_figs.py` 即可；
3. **表格完整性**：`insert_figs.py` 采用**字符串级精确替换**（早期按段落重排会丢 `w:tbl` 结构），
 生成后请核对"表格数 > 0"（脚本会打印）。
