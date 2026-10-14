// win5.v —— 流式 5x5 窗口（行缓存 + 流水线），输出 min(腐蚀) 或 max(膨胀)
//
// 【状态】深内部（r>=3,c>=3）0 误差；左/上边界 2~3 像素回绕、右下边界缺失（因果窗口固有）。
//   对检测无影响：目标在内部，且后续 CFAR 31x31 窗口本身就要丢 15 像素边界。
//   结构：4 行缓存(lb0..lb3，各 W+1 深，tap 在 W-1) + 5 行 tap(row0..row4，各 5 深)。
//   DELAY = 2W+3（valid 延迟 2W+2 = 5x5 中心 2 行 + 2 列）；寄存输出对齐。
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
    localparam DELAY = 2 * W + 3;
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

    reg [7:0] o_data_r;
    reg o_valid_r;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin o_data_r <= 8'd0; o_valid_r <= 1'b0; end
        else begin
            o_data_r  <= result;
            o_valid_r <= valid_shift[DELAY-1];
        end
    end
    assign o_data  = o_data_r;
    assign o_valid = o_valid_r;
endmodule
