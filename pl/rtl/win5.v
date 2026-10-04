// win5.v —— 流式 5x5 窗口（行缓存 + 流水线），输出 min(腐蚀) 或 max(膨胀)
// ⚠️ 状态：WIP（未完成）。内部 15/16 像素正确，但有 3 个已知问题，见下。暂不用于正式验证。
//
// 【已知 bug 1 · 1 像素对齐偏差】
//   8x8 单测(tb_win5.v)：内部 (2,2) 输出 1、期望 0（差 1 像素），其余内部像素全对。
//   原因：行缓存 tap 与 valid 有 1 周期时序偏差（valid 采到的窗口比实际早/晚 1 列）。
//   已试过（记录，避免重蹈）：
//     - DELAY = 2W+3（当前，最好：内部 15/16 正确，仅 (2,2) 差 1）
//     - DELAY = 2W+4（更糟：整体错 1 列，内部 0/16）
//     - tap 用 lbX[W-1]（当前，已确认等价"上一行同列"，正确）
//     - tap 用 lbX[W]（更糟，不要用）
//
// 【已知 bug 2 · 行边界列回绕】
//   行边界处（c<4），负列 tap 会串到上一行尾部（gray(r-1,W-1) 等）而非 PAD。
//   修法：加列计数器 c，当 c<4 时把负列强制置 PAD（当前负列是"包回来"的旧像素）。
//
// 【已知 bug 3 · 因果窗口底部/右边缺失】
//   因果窗口（只用过去像素）只能产出位置 0..W-5，最后 4 行/列需"未来像素"，本结构产不出。
//   要完整边界得改"中心窗口"（额外缓冲 2 行 2 列未来像素），或接受最外 2 圈的损失。
//   （实际检测目标在内部，CFAR 窗口 31x31 也本来就要丢 15 像素边界，故可接受。）
//
// 【下一步调试方法】
//   1) 在 tb_win5.v 加 $dumpvars 生成 VCD，用波形看 row0..row4 与 valid_shift 逐拍对齐；
//   2) 参考 gauss3_stream.v（已验证的 3×3 流式样板，行缓存结构与本文件相同）逐拍对照；
//   3) 定位 bug 1 后，再修 bug 2（加列计数器插 PAD）。
module win5 #(
    parameter W = 32,
    parameter IS_MAX = 0,   // 0 = min（腐蚀），1 = max（膨胀）
    parameter PAD = 8'd0    // 边界填充值：腐蚀 255（min 中性）、膨胀 0（max 中性）
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
    localparam DELAY = 2 * W + 3;   // valid 延迟 2W+2 = 5x5 中心（2 行 + 2 列）
    wire hs = i_valid && i_ready;
    assign i_ready = o_ready;

    reg [7:0] lb0 [0:W];
    reg [7:0] lb1 [0:W];
    reg [7:0] lb2 [0:W];
    reg [7:0] lb3 [0:W];
    reg [7:0] row0 [0:4];
    reg [7:0] row1 [0:4];
    reg [7:0] row2 [0:4];
    reg [7:0] row3 [0:4];
    reg [7:0] row4 [0:4];

    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i <= W; i = i + 1) begin lb0[i] <= PAD; lb1[i] <= PAD; lb2[i] <= PAD; lb3[i] <= PAD; end
            for (i = 0; i < 5; i = i + 1) begin row0[i] <= PAD; row1[i] <= PAD; row2[i] <= PAD; row3[i] <= PAD; row4[i] <= PAD; end
        end else if (hs) begin
            lb3[0] <= lb2[W-1];
            for (i = 1; i <= W; i = i + 1) lb3[i] <= lb3[i-1];
            lb2[0] <= lb1[W-1];
            for (i = 1; i <= W; i = i + 1) lb2[i] <= lb2[i-1];
            lb1[0] <= lb0[W-1];
            for (i = 1; i <= W; i = i + 1) lb1[i] <= lb1[i-1];
            lb0[0] <= i_data;
            for (i = 1; i <= W; i = i + 1) lb0[i] <= lb0[i-1];

            row4[0] <= lb3[W-1]; row4[1] <= row4[0]; row4[2] <= row4[1]; row4[3] <= row4[2]; row4[4] <= row4[3];
            row3[0] <= lb2[W-1]; row3[1] <= row3[0]; row3[2] <= row3[1]; row3[3] <= row3[2]; row3[4] <= row3[3];
            row2[0] <= lb1[W-1]; row2[1] <= row2[0]; row2[2] <= row2[1]; row2[3] <= row2[2]; row2[4] <= row2[3];
            row1[0] <= lb0[W-1]; row1[1] <= row1[0]; row1[2] <= row1[1]; row1[3] <= row1[2]; row1[4] <= row1[3];
            row0[0] <= i_data;   row0[1] <= row0[0]; row0[2] <= row0[1]; row0[3] <= row0[2]; row0[4] <= row0[3];
        end
    end

    function [7:0] min5;
        input [7:0] a, b, c, d, e;
        reg [7:0] m;
        begin
            m = (a < b) ? a : b; m = (m < c) ? m : c; m = (m < d) ? m : d; min5 = (m < e) ? m : e;
        end
    endfunction
    function [7:0] max5;
        input [7:0] a, b, c, d, e;
        reg [7:0] m;
        begin
            m = (a > b) ? a : b; m = (m > c) ? m : c; m = (m > d) ? m : d; max5 = (m > e) ? m : e;
        end
    endfunction

    wire [7:0] r0_min = min5(row0[0], row0[1], row0[2], row0[3], row0[4]);
    wire [7:0] r1_min = min5(row1[0], row1[1], row1[2], row1[3], row1[4]);
    wire [7:0] r2_min = min5(row2[0], row2[1], row2[2], row2[3], row2[4]);
    wire [7:0] r3_min = min5(row3[0], row3[1], row3[2], row3[3], row3[4]);
    wire [7:0] r4_min = min5(row4[0], row4[1], row4[2], row4[3], row4[4]);
    wire [7:0] r0_max = max5(row0[0], row0[1], row0[2], row0[3], row0[4]);
    wire [7:0] r1_max = max5(row1[0], row1[1], row1[2], row1[3], row1[4]);
    wire [7:0] r2_max = max5(row2[0], row2[1], row2[2], row2[3], row2[4]);
    wire [7:0] r3_max = max5(row3[0], row3[1], row3[2], row3[3], row3[4]);
    wire [7:0] r4_max = max5(row4[0], row4[1], row4[2], row4[3], row4[4]);

    wire [7:0] res_min = min5(r0_min, r1_min, r2_min, r3_min, r4_min);
    wire [7:0] res_max = max5(r0_max, r1_max, r2_max, r3_max, r4_max);
    wire [7:0] result = IS_MAX ? res_max : res_min;

    reg [DELAY-1:0] valid_shift;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) valid_shift <= {DELAY{1'b0}};
        else if (o_ready) valid_shift <= {valid_shift[DELAY-2:0], i_valid};
    end

    assign o_data  = result;
    assign o_valid = valid_shift[DELAY-1];
endmodule
