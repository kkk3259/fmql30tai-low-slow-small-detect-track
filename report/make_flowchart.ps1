# 用 PowerPoint COM 画 1.6 设计流程图（4 阶段横向流程）
$ErrorActionPreference = "Continue"
$OUT = Join-Path $PSScriptRoot "figs\图H_设计流程图.png"

$ppt = New-Object -ComObject PowerPoint.Application
try {
    $pres = $ppt.Presentations.Add($false)      # 不显示窗口
    # 幻灯片尺寸：pt（1 pt = 12700 EMU）
    $pres.PageSetup.SlideWidth = 960
    $pres.PageSetup.SlideHeight = 262

    $slide = $pres.Slides.Add(1, 12)            # ppLayoutBlank = 12

    # ── 配色 ──
    $cTitle = 0x96542F      # 深蓝 #2F5496（COM 为 BGR 顺序）
    $cBody  = 0x4A4A4A
    $cBox   = 0xF0E8E8      # 浅蓝灰 #E8E8F0（BGR）
    $cLine  = 0x9A9A9A

    $stages = @(
        @{ X = 20;  No = "①"; Title = "需求分解";       L1 = "目标特性与平台约束"; L2 = "任务划入 PS/NPU/PL"; L3 = "三级执行域" },
        @{ X = 255; No = "②"; Title = "软件基线与标定"; L1 = "v0 预处理 · v1 检测"; L2 = "v2 跟踪 + 评测脚本"; L3 = "网格扫描定参数工作点" },
        @{ X = 490; No = "③"; Title = "硬件迁移";       L1 = "逐模块 Verilog 实现"; L2 = "配套 Testbench"; L3 = "仿真期与 OpenCV 比对" },
        @{ X = 725; No = "④"; Title = "系统集成";       L1 = "PS 编排 · PL 上板"; L2 = "NPU 部署 · 交叉验证"; L3 = "预留 5 处硬件替换点" }
    )

    $W = 215; $H = 150; $T = 55

    foreach ($s in $stages) {
        # 圆角矩形
        $sh = $slide.Shapes.AddShape(5, $s.X, $T, $W, $H)   # msoShapeRoundedRectangle
        $sh.Fill.ForeColor.RGB = $cBox
        $sh.Fill.Solid()
        $sh.Line.ForeColor.RGB = $cTitle
        $sh.Line.Weight = 1.5
        $sh.Adjustments.Item(1) = 0.06

        # 阶段标题
        $tb = $slide.Shapes.AddTextbox(1, $s.X + 6, $T + 8, $W - 12, 26)
        $tf = $tb.TextFrame
        $tf.WordWrap = $true
        $tf.MarginLeft = 0; $tf.MarginRight = 0; $tf.MarginTop = 0; $tf.MarginBottom = 0
        $tr = $tf.TextRange
        $tr.Text = "$($s.No) $($s.Title)"
        $tr.Font.Size = 13
        $tr.Font.Bold = $true
        $tr.Font.Name = "微软雅黑"
        $tr.Font.NameFarEast = "微软雅黑"
        $tr.Font.Color.RGB = $cTitle
        $tr.ParagraphFormat.Alignment = 2      # ppAlignCenter

        # 正文三行
        $tb2 = $slide.Shapes.AddTextbox(1, $s.X + 8, $T + 42, $W - 16, $H - 50)
        $tf2 = $tb2.TextFrame
        $tf2.WordWrap = $true
        $tf2.MarginLeft = 0; $tf2.MarginRight = 0; $tf2.MarginTop = 0; $tf2.MarginBottom = 0
        $tr2 = $tf2.TextRange
        $tr2.Text = "$($s.L1)`r$($s.L2)`r$($s.L3)"
        $tr2.Font.Size = 10.5
        $tr2.Font.Name = "微软雅黑"
        $tr2.Font.NameFarEast = "微软雅黑"
        $tr2.Font.Color.RGB = $cBody
        $tr2.ParagraphFormat.Alignment = 2
        $tr2.ParagraphFormat.SpaceWithin = 1.2
    }

    # ── 三个箭头 ──
    for ($i = 0; $i -lt 3; $i++) {
        $x1 = $stages[$i].X + $W + 2
        $x2 = $stages[$i + 1].X - 2
        $y = $T + $H / 2
        $cn = $slide.Shapes.AddConnector(1, $x1, $y, $x2, $y)   # msoConnectorStraight
        $cn.Line.ForeColor.RGB = $cTitle
        $cn.Line.Weight = 2.25
        $cn.Line.EndArrowheadStyle = 3                          # msoArrowheadTriangle
        $cn.Line.EndArrowheadLength = 2
        $cn.Line.EndArrowheadWidth = 2
    }

    # ── 顶部标题 ──
    $tt = $slide.Shapes.AddTextbox(1, 20, 8, 920, 32)
    $tft = $tt.TextFrame
    $tft.MarginLeft = 0; $tft.MarginTop = 0; $tft.MarginRight = 0; $tft.MarginBottom = 0
    $trt = $tft.TextRange
    $trt.Text = "先软后硬、以软验硬——四阶段与各阶段可验证交付物"
    $trt.Font.Size = 15
    $trt.Font.Bold = $true
    $trt.Font.Name = "微软雅黑"
    $trt.Font.NameFarEast = "微软雅黑"
    $trt.Font.Color.RGB = $cTitle
    $trt.ParagraphFormat.Alignment = 2

    # ── 底部注释 ──
    $ft = $slide.Shapes.AddTextbox(1, 20, $T + $H + 18, 920, 28)
    $tff = $ft.TextFrame
    $tff.MarginLeft = 0; $tff.MarginTop = 0; $tff.MarginRight = 0; $tff.MarginBottom = 0
    $trf = $tff.TextRange
    $trf.Text = "关键约束：算法在 PC 端验证通过后才写 RTL；仿真阶段即完成逐像素比对；硬件替换点使软硬件可渐进切换"
    $trf.Font.Size = 10
    $trf.Font.Name = "微软雅黑"
    $trf.Font.NameFarEast = "微软雅黑"
    $trf.Font.Color.RGB = $cLine
    $trf.ParagraphFormat.Alignment = 2

    # ── 导出 PNG ──
    if (Test-Path $OUT) { Remove-Item $OUT -Force }
    $slide.Export($OUT, "PNG", 1920, 524)
    Write-Output ("  已导出: " + $OUT)

    $pres.Close()
    Write-Output "  完成"
} catch {
    Write-Output ("  FAIL: " + $_.Exception.Message)
} finally {
    try { $ppt.Quit() } catch {}
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null
}

if (Test-Path $OUT) {
    $i = Get-Item $OUT
    Write-Output ("  文件大小: {0:N0} KB" -f ($i.Length/1KB))
}
