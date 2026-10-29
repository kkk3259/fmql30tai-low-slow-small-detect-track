// tophat_5x5_stream.v —— 流式 NxN Top-Hat / Black-Hat（行缓存 + 流水线）
// TopHat   = I - opening(I) = I - dilate(erode(I,SE),SE)      → 亮小目标
// BlackHat = closing(I) - I = erode(dilate(I,SE),SE) - I      → 暗小目标
// 【2026-10-29】新增 MODE：0=Top-Hat（默认，检亮目标）、1=Black-Hat（检暗目标）。
//   S 的实测（tools/bench_cfar_tradeoff.py，100 张真实图）：真实目标是**暗点**，
//   Black-Hat k=3.0 召回 86%/候选 47.5，优于 Top-Hat k=4.0 的 55%/34.7。
//   硬件无需新增资源：两级 win5 的 IS_MAX/PAD 对调、减法方向反过来即可。
// ✅ 已验证（SE=5）：内部逐像素与 cv2.morphologyEx(MORPH_TOPHAT, 5x5) 0 误差。
// 【2026-10-28】SE 参数化，默认 21x21（SE=5 只能检 1~4px，SE=21 可检 <=20px）。
// 结构：win5(第1级) → win5(第2级) → 原始延迟 TD 对齐。
// TD = 2*(每级 win5 延迟) + 1，每级延迟 = (SE/2)*W + (SE/2) + 1。
module tophat_5x5_stream #(
    parameter W = 32,
    parameter H = 32,
    parameter SE = 5,                                       // 结构元边长（奇数）；默认 5
    parameter MODE = 0,                                     // 0=Top-Hat(亮) 1=Black-Hat(暗)
    parameter TD = 2*(((SE/2)*W) + (SE/2) + 1) + 1           // 原始灰度延迟（对齐 opening）
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] i_data,
    input  wire i_valid,
    output wire i_ready,
    output wire [7:0] o_data,
    output wire o_valid,
    input  wire o_ready
);
    // TD 已改为参数（见模块声明），用于扫描对齐延迟

    wire [7:0] eroded;
    wire eroded_valid;
    wire eroded_ready;
    // 第 1 级：Top-Hat 用腐蚀(min,pad255)，Black-Hat 用膨胀(max,pad0)
    win5 #(.W(W), .SE(SE), .IS_MAX(MODE ? 1 : 0), .PAD(MODE ? 8'd0 : 8'd255)) u_erode (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid), .i_ready(i_ready),
        .o_data(eroded), .o_valid(eroded_valid), .o_ready(eroded_ready)
    );

    wire [7:0] dilated;
    wire dilated_valid;
    wire dilated_ready;
    // 第 2 级：Top-Hat 用膨胀(max,pad0)，Black-Hat 用腐蚀(min,pad255)
    win5 #(.W(W), .SE(SE), .IS_MAX(MODE ? 0 : 1), .PAD(MODE ? 8'd255 : 8'd0)) u_dilate (
        .clk(clk), .rst_n(rst_n),
        .i_data(eroded), .i_valid(eroded_valid), .i_ready(eroded_ready),
        .o_data(dilated), .o_valid(dilated_valid), .o_ready(o_ready)
    );

    // 原始灰度延迟（对齐 opening）
    // 【2026-10 重构】原为 gd[0:TD] 移位寄存器（W=640 时 TD=2567 → 20,544 个触发器）。
    // 现改为循环 RAM 延迟线：深度 TD+2、延迟 TD+1 拍（等价原 gd[TD] 抽头：
    // 原式 gd[TD]=x_{t-1-TD}），同一指针的读地址 rp=(wp+1) mod (TD+2) 取出该值；
    // 填充不足 TD+1 拍时输出 0（等价原复位值全 0）。
    localparam GD_D = TD + 2;            // 循环缓冲深度
    localparam GD_LAT = TD + 1;          // 延迟拍数
    localparam GPW = $clog2(GD_D);       // 指针位宽

    reg [7:0] gd [0:GD_D-1];
    reg [GPW-1:0] gwp;
    reg [GPW-1:0] gfill;

    wire hs = i_valid && i_ready;
    wire [GPW-1:0] grp = (gwp == GD_D[GPW-1:0] - 1'b1) ? {GPW{1'b0}} : (gwp + 1'b1);
    wire gfull = (gfill >= GD_LAT[GPW-1:0]);

    // 独立 always 写块（标准 1写1读 RAM 写法，便于综合推断 RAM）
    // 【Vivado 兼容】同步复位（原因见 win5.v 同处注释：Vivado 拒绝带异步复位的 RAM 写块）
    always @(posedge clk) begin
        if (!rst_n) begin
            gwp   <= {GPW{1'b0}};
            gfill <= {GPW{1'b0}};
        end else if (hs) begin
            gd[gwp] <= i_data;
            if (gwp == GD_D[GPW-1:0] - 1'b1) gwp <= {GPW{1'b0}};
            else                             gwp <= gwp + 1'b1;
            if (gfill < GD_LAT[GPW-1:0]) gfill <= gfill + 1'b1;
        end
    end

    wire [7:0] gray_c = gfull ? gd[grp] : 8'd0;
    // MODE=0: TopHat   = I - opening  → 亮目标
    // MODE=1: BlackHat = closing - I  → 暗目标
    wire [7:0] th_t = (gray_c >= dilated) ? (gray_c - dilated) : 8'd0;
    wire [7:0] th_b = (dilated >= gray_c) ? (dilated - gray_c) : 8'd0;
    wire [7:0] th   = MODE ? th_b : th_t;

    // 寄存输出（与 win5 对齐，标准流式；带 o_ready 使能，受阻时必须保持数据）
    reg [7:0] o_data_r;
    reg o_valid_r;
    reg [7:0] o_data_r2;
    reg o_valid_r2;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            o_data_r <= 8'd0; o_valid_r <= 1'b0;
            o_data_r2 <= 8'd0; o_valid_r2 <= 1'b0;
        end else if (o_ready) begin
            o_data_r  <= th;
            o_valid_r <= dilated_valid;
            // 数据多打一拍：参数化后数据比 valid 早 1 个样本（实测 new[i]=old[i+1]）
            o_data_r2  <= o_data_r;
            o_valid_r2 <= o_valid_r;
        end
    end
    // 输出：数据两拍、valid 一拍（数据比 valid 晚 1 个样本，与历史版本逐样本一致）
    assign o_data  = o_data_r2;
    assign o_valid = o_valid_r;
endmodule
