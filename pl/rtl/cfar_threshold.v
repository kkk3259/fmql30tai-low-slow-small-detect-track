// cfar_threshold.v —— IP2 子模块②：CFAR 自适应阈值（定点 MAD + 积分图滑动盒式滤波）
// thr = 局部均值 + k×局部MAD + floor（31x31 窗口）；img > thr 判为目标(255)，否则 0
// 积分图：把 31x31 窗口求和从 O(961) 降到 O(1)（4 次查表+3 次加减），640x360 也能实时。
// 定点化：整数 MAD 替代 real+$sqrt，避开开方（MAD≈0.8×std，故 k 由 4.0 调成 5）。
module cfar_threshold #(
    parameter W = 64,
    parameter H = 64,
    parameter WIN = 31,      // 窗口尺寸
    parameter K = 5,         // MAD 系数（近似 std 的 k=4.0）
    parameter FLOOR = 3      // 阈值下限
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] i_data,
    input  wire i_valid,
    output reg  [7:0] o_data,
    output reg  o_valid,
    input  wire o_ready
);
    localparam N = W * H;
    localparam CW = $clog2(W);
    localparam CH = $clog2(H);
    localparam CNT_W = CW + CH;
    localparam WIN_AREA = WIN * WIN;   // 961
    localparam HALF = WIN / 2;         // 15
    localparam INT_W = $clog2(N * 255) + 1;

    reg [7:0] img [0:H-1][0:W-1];
    reg [7:0] bin [0:H-1][0:W-1];
    reg [INT_W-1:0] integral [0:H-1][0:W-1];   // 积分图（img 与 |img-mu| 复用）
    reg [7:0] mu  [0:H-1][0:W-1];
    reg [7:0] abs_mem [0:H-1][0:W-1];

    reg [CNT_W-1:0] cnt;
    reg [INT_W-1:0] row_sum;
    reg [2:0] state;
    localparam S_IN = 0, S_INT1 = 1, S_MU = 2, S_INT2 = 3, S_BIN = 4, S_OUT = 5, S_DONE = 6;

    wire [CH-1:0] r = cnt / W;      // 行（真除法，支持非 2 幂宽）
    wire [CW-1:0] c = cnt % W;      // 列（取余）

    // 积分图 O(1) 盒求和（窗口 clamp）
    integer bx1, by1, bx2, by2;
    reg [INT_W-1:0] box_c;
    reg [10:0] win_area_c;
    always @* begin
        bx1 = (c < HALF) ? 0 : (c - HALF);
        bx2 = (c + HALF >= W) ? (W - 1) : (c + HALF);
        by1 = (r < HALF) ? 0 : (r - HALF);
        by2 = (r + HALF >= H) ? (H - 1) : (r + HALF);
        box_c = integral[by2][bx2];
        if (by1 > 0) box_c = box_c - integral[by1 - 1][bx2];
        if (bx1 > 0) box_c = box_c - integral[by2][bx1 - 1];
        if (by1 > 0 && bx1 > 0) box_c = box_c + integral[by1 - 1][bx1 - 1];
        win_area_c = (bx2 - bx1 + 1) * (by2 - by1 + 1);   // 裁剪窗口实际像素数（边界变小）
    end

    wire [7:0] mean_c = box_c / win_area_c;   // S_MU 时是均值，S_BIN 时是 MAD（裁剪边界）

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 0; state <= S_IN; o_data <= 8'd0; o_valid <= 1'b0; row_sum <= 0;
        end else begin
            case (state)
                S_IN: begin
                    if (i_valid) begin
                        img[r][c] <= i_data;
                        if (cnt == N - 1) begin state <= S_INT1; cnt <= 0; row_sum <= 0; end
                        else cnt <= cnt + 1;
                    end
                end
                // 积分图：img
                S_INT1: begin
                    if (c == 0) row_sum <= img[r][c];
                    else        row_sum <= row_sum + img[r][c];
                    integral[r][c] <= ((c == 0) ? img[r][c] : (row_sum + img[r][c]))
                                      + ((r == 0) ? 0 : integral[r-1][c]);
                    if (cnt == N - 1) begin state <= S_MU; cnt <= 0; end
                    else cnt <= cnt + 1;
                end
                // 均值 + 绝对偏差
                S_MU: begin
                    mu[r][c]      <= mean_c;
                    abs_mem[r][c] <= (img[r][c] >= mean_c) ? (img[r][c] - mean_c) : (mean_c - img[r][c]);
                    if (cnt == N - 1) begin state <= S_INT2; cnt <= 0; row_sum <= 0; end
                    else cnt <= cnt + 1;
                end
                // 积分图：|img-mu|
                S_INT2: begin
                    if (c == 0) row_sum <= abs_mem[r][c];
                    else        row_sum <= row_sum + abs_mem[r][c];
                    integral[r][c] <= ((c == 0) ? abs_mem[r][c] : (row_sum + abs_mem[r][c]))
                                      + ((r == 0) ? 0 : integral[r-1][c]);
                    if (cnt == N - 1) begin state <= S_BIN; cnt <= 0; end
                    else cnt <= cnt + 1;
                end
                // 二值化：img > mu + k*MAD + floor
                S_BIN: begin
                    bin[r][c] <= (img[r][c] > (mu[r][c] + K * mean_c + FLOOR)) ? 8'd255 : 8'd0;
                    if (cnt == N - 1) begin state <= S_OUT; cnt <= 0; end
                    else cnt <= cnt + 1;
                end
                S_OUT: begin
                    o_data  <= bin[r][c];
                    o_valid <= 1'b1;
                    if (o_ready) begin
                        if (cnt == N - 1) state <= S_DONE;
                        else cnt <= cnt + 1;
                    end
                end
                S_DONE: o_valid <= 1'b0;
            endcase
        end
    end
endmodule
