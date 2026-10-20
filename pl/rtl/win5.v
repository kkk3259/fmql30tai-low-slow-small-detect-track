// win5.v —— 流式 5x5 窗口（行缓存 + 流水线），输出 min(腐蚀) 或 max(膨胀)
//
// 【状态】深内部（r>=3,c>=3）0 误差；左/上边界 2~3 像素回绕、右下边界缺失（因果窗口固有）。
//   对检测无影响：目标在内部，且后续 CFAR 31x31 窗口本身就要丢 15 像素边界。
//   结构：4 条延迟行(lb0..lb3) + 5 行 tap(row0..row4，各 5 深)。
//   DELAY = 2W+3（valid 延迟 2W+2 = 5x5 中心 2 行 + 2 列）；寄存输出对齐。
//
// 【2026-10 重构】lb0..lb3 原来是移位寄存器（W=640 时 4×641×8 = 20512 个触发器，
//   两个 win5 实例共 41K FF，是综合后 88K 触发器的主因）。
//   现改为"循环 RAM 延迟线"：深度 W+1、延迟 W 拍，四条行共用同一个写指针 wp，
//   读地址 rp=(wp+1) mod (W+1) 恰好取出 W 拍前写入的值，与原移位寄存器逐拍等价
//   （fill<W 期间读未写过的槽位，输出 PAD，等价原来的全 PAD 复位值）。
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
    localparam DLY = W;              // 每条行缓存延迟拍数（与原移位寄存器 lb[W-1] 抽头一致）
    localparam DEPTH = W + 1;        // 循环缓冲深度
    localparam PW = $clog2(DEPTH);   // 指针位宽

    wire hs = i_valid && i_ready;
    assign i_ready = o_ready;

    // 循环延迟线（4 条行缓存）：写指针 wp，读指针 rp 取出 DLY 拍前的数据
    reg [7:0] lb0 [0:W];
    reg [7:0] lb1 [0:W];
    reg [7:0] lb2 [0:W];
    reg [7:0] lb3 [0:W];

    // 5x5 窗口的 5 行抽头（每行 5 深移位，只有 40 个触发器，保留寄存器实现）
    reg [7:0] row0 [0:4];
    reg [7:0] row1 [0:4];
    reg [7:0] row2 [0:4];
    reg [7:0] row3 [0:4];
    reg [7:0] row4 [0:4];

    reg [PW-1:0] wp;      // 写指针 0..W
    reg [PW-1:0] fill;    // 已填充拍数，饱和于 DLY

    wire [PW-1:0] rp = (wp == DEPTH[PW-1:0] - 1'b1) ? {PW{1'b0}} : (wp + 1'b1);
    wire full = (fill >= DLY[PW-1:0]);

    wire [7:0] t0 = full ? lb0[rp] : PAD;
    wire [7:0] t1 = full ? lb1[rp] : PAD;
    wire [7:0] t2 = full ? lb2[rp] : PAD;
    wire [7:0] t3 = full ? lb3[rp] : PAD;

    integer i;

    // ---- 延迟线写块（独立 always，标准 1写1读 RAM 写法，便于综合推断 RAM）----
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wp   <= {PW{1'b0}};
            fill <= {PW{1'b0}};
        end else if (hs) begin
            lb0[wp] <= i_data;
            lb1[wp] <= t0;
            lb2[wp] <= t1;
            lb3[wp] <= t2;
            if (wp == DEPTH[PW-1:0] - 1'b1) wp <= {PW{1'b0}};
            else                            wp <= wp + 1'b1;
            if (fill < DLY[PW-1:0]) fill <= fill + 1'b1;
        end
    end

    // ---- 5 行抽头移位（等价原 row0..row4 移位链）----
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i < 5; i = i + 1) begin
                row0[i] <= PAD; row1[i] <= PAD; row2[i] <= PAD; row3[i] <= PAD; row4[i] <= PAD;
            end
        end else if (hs) begin
            row4[0] <= t3;
            row3[0] <= t2;
            row2[0] <= t1;
            row1[0] <= t0;
            row0[0] <= i_data;
            for (i = 1; i < 5; i = i + 1) begin
                row0[i] <= row0[i-1]; row1[i] <= row1[i-1]; row2[i] <= row2[i-1];
                row3[i] <= row3[i-1]; row4[i] <= row4[i-1];
            end
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
        else if (o_ready) begin
            o_data_r  <= result;
            o_valid_r <= valid_shift[DELAY-1];
        end
    end
    assign o_data  = o_data_r;
    assign o_valid = o_valid_r;
endmodule
