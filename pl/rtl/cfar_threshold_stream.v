// cfar_threshold_stream.v —— 流式 CFAR 自适应阈值（中心窗口滑动盒，综合友好，无死区）
//
// 【重构要点】替代全帧积分图（全帧 2D 数组 + 除法索引，综合器推不出 BRAM）。
//   滑动盒 O(1) 求和（中心窗口，无偏移无死区）：
//     - delay[0..31W] 深度延迟线 → "离开窗口"像素（31 行上同列）
//     - col_sum[0..W+14] 列和数组（加宽到 W+15，容纳中心窗口的"未来列"）→ 每列 31 行竖直和
//     - fifo[0..30] 31 项移位寄存器 → 水平窗口
//     - window_sum = new_colsum + sum(fifo[0..29])
//   S_LOAD 只存图像 N 像素；S_MEAN/S_MAD 在虚拟行列序（行 0..H+14、列 0..W+14）下处理，
//   PAD 位置 cur_px=0。中心 (crow,ccol)=(row-15,col-15)，输出覆盖全帧 N 像素（无偏移无死区）。
//
// 阈值：thr = mean + K×MAD + FLOOR，img > thr 判目标(255)。
module cfar_threshold_stream #(
    parameter W = 64,
    parameter H = 64,
    parameter WIN = 31,
    parameter K = 5,
    parameter FLOOR = 3
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] i_data,
    input  wire i_valid,
    output wire i_ready,
    output wire [7:0] o_data,   // 二值图（255/0）
    output wire [7:0] o_enh,    // 对齐的增强图（中心像素，与 o_data 同位置）
    output wire o_valid,
    input  wire o_ready
);
    localparam N = W * H;
    localparam HALF = WIN / 2;                       // 15
    localparam W15 = W + HALF;                       // 虚拟列宽 W+15
    localparam H15 = H + HALF;                       // 虚拟行高 H+15
    localparam N_TOTAL = H15 * W15;                  // 虚拟总像素
    localparam CENTER_OFF = HALF * W + HALF;         // 图像中心偏移 15W+15
    localparam CNT_W = $clog2(N_TOTAL + 1);
    localparam CW = $clog2(W15 + 1);                 // 虚拟列位宽
    localparam CH = $clog2(H15 + 1);                 // 虚拟行位宽
    localparam WIN_AREA = WIN * WIN;                 // 961
    localparam SUM_W = $clog2(WIN_AREA * 255) + 1;   // 盒和位宽
    localparam DELAY_D = WIN * W15;                  // 31×(W+15) 延迟线深度（虚拟行宽）

    reg [7:0]  img_bram  [0:N-1];
    reg [7:0]  mean_bram [0:N-1];

    reg [7:0] delay [0:DELAY_D];
    reg [SUM_W-1:0] col_sum [0:W15-1];
    reg [SUM_W-1:0] fifo [0:WIN-1];
    reg [CW-1:0] col;
    reg [CH-1:0] row;
    reg [CNT_W-1:0] cnt;      // S_MEAN/S_MAD 的虚拟计数
    reg [CNT_W-1:0] load_cnt; // S_LOAD 的图像计数
    reg [CNT_W-1:0] cflat;    // 当前图像 flat（0..N-1，仅图像位置递增）
    reg [CNT_W-1:0] ccnt;     // 中心图像 flat（0..N-1，仅有效中心递增）

    reg [2:0] state;
    localparam S_LOAD = 0, S_MEAN = 1, S_MAD = 2, S_DONE = 3;

    integer i;

    // ---- 当前像素（虚拟位置；PAD 位置为 0）----
    wire is_img = (row < H) && (col < W);
    wire [7:0] cur_px = is_img ? img_bram[cflat] : 8'd0;

    // 局部均值（abs_dev 用）：PAD 位置按 0
    wire [7:0] mean_local = is_img ? mean_bram[cflat] : 8'd0;
    // 中心均值（阈值用）：ccnt = 中心图像 flat
    wire [7:0] mean_center = mean_bram[ccnt];
    wire [7:0] abs_d = (cur_px >= mean_local) ? (cur_px - mean_local) : (mean_local - cur_px);
    wire [7:0] cur_val = (state == S_MEAN) ? cur_px : abs_d;

    // ---- 滑动盒窗口和 ----
    wire [SUM_W-1:0] new_colsum = col_sum[col] + {1'b0, cur_val} - {1'b0, delay[DELAY_D]};
    wire [SUM_W-1:0] window_sum = new_colsum + fifo[0] + fifo[1] + fifo[2] + fifo[3] + fifo[4] +
                                  fifo[5] + fifo[6] + fifo[7] + fifo[8] + fifo[9] + fifo[10] +
                                  fifo[11] + fifo[12] + fifo[13] + fifo[14] + fifo[15] + fifo[16] +
                                  fifo[17] + fifo[18] + fifo[19] + fifo[20] + fifo[21] + fifo[22] +
                                  fifo[23] + fifo[24] + fifo[25] + fifo[26] + fifo[27] + fifo[28] + fifo[29];

    // ---- 中心坐标与裁剪面积（中心窗口，与全帧版积分图裁剪一致）----
    wire [CH-1:0] crow = row - HALF;   // 中心行（row>=15 有效）
    wire [CW-1:0] ccol = col - HALF;   // 中心列（col>=15 有效）
    wire [5:0] crow_cnt = (crow < HALF) ? (crow + HALF + 1) : ((crow >= H - HALF) ? (H + HALF - crow) : WIN[5:0]);
    wire [5:0] ccol_cnt = (ccol < HALF) ? (ccol + HALF + 1) : ((ccol >= W - HALF) ? (W + HALF - ccol) : WIN[5:0]);
    wire [11:0] win_area_raw = crow_cnt * ccol_cnt;
    wire [10:0] win_area_c = (win_area_raw == 12'd0) ? 11'd1 : win_area_raw[10:0];

    // 盒均值 / MAD（变量除法，综合时换倒数 LUT）
    wire [7:0] box_avg = window_sum / win_area_c;
    wire [16:0] thr = {9'd0, mean_center} + K * {9'd0, box_avg} + FLOOR;
    // 中心像素（ccnt = 中心图像 flat）
    wire [7:0] center_px = img_bram[ccnt];

    reg [7:0] o_data_r;
    reg [7:0] o_enh_r;
    reg o_valid_r;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i <= DELAY_D; i = i + 1) delay[i] <= 8'd0;
            for (i = 0; i < W15; i = i + 1) col_sum[i] <= 0;
            for (i = 0; i < WIN; i = i + 1) fifo[i] <= 0;
            col <= 0; row <= 0; cnt <= 0; load_cnt <= 0; cflat <= 0; ccnt <= 0; state <= S_LOAD;
            o_data_r <= 8'd0; o_enh_r <= 8'd0; o_valid_r <= 1'b0;
        end else begin
            o_valid_r <= 1'b0;
            case (state)
            S_LOAD: begin
                if (i_valid) begin
                    img_bram[load_cnt] <= i_data;
                    if (load_cnt == N - 1) begin state <= S_MEAN; cnt <= 0; col <= 0; row <= 0; cflat <= 0; ccnt <= 0; end
                    else load_cnt <= load_cnt + 1;
                end
            end
            S_MEAN: begin
                delay[0] <= cur_px;
                for (i = 1; i <= DELAY_D; i = i + 1) delay[i] <= delay[i-1];
                col_sum[col] <= new_colsum;
                fifo[0] <= new_colsum;
                if (col == 0) begin
                    for (i = 1; i < WIN; i = i + 1) fifo[i] <= 0;
                end else begin
                    for (i = 1; i < WIN; i = i + 1) fifo[i] <= fifo[i-1];
                end
                if (row >= HALF && col >= HALF) mean_bram[ccnt] <= box_avg;
                if (cnt == N_TOTAL - 1) begin
                    state <= S_MAD; cnt <= 0; col <= 0; row <= 0; cflat <= 0; ccnt <= 0;
                    for (i = 0; i <= DELAY_D; i = i + 1) delay[i] <= 8'd0;
                    for (i = 0; i < W15; i = i + 1) col_sum[i] <= 0;
                    for (i = 0; i < WIN; i = i + 1) fifo[i] <= 0;
                end else begin
                    cnt <= cnt + 1;
                    if (col == W15 - 1) begin col <= 0; row <= row + 1; end else col <= col + 1;
                    if (is_img) cflat <= cflat + 1;
                    if (row >= HALF && col >= HALF) ccnt <= ccnt + 1;
                end
            end
            S_MAD: begin
                delay[0] <= abs_d;
                for (i = 1; i <= DELAY_D; i = i + 1) delay[i] <= delay[i-1];
                col_sum[col] <= new_colsum;
                fifo[0] <= new_colsum;
                if (col == 0) begin
                    for (i = 1; i < WIN; i = i + 1) fifo[i] <= 0;
                end else begin
                    for (i = 1; i < WIN; i = i + 1) fifo[i] <= fifo[i-1];
                end
                o_data_r <= (center_px > thr[7:0]) ? 8'd255 : 8'd0;
                o_enh_r  <= center_px;
                o_valid_r <= (row >= HALF) && (col >= HALF) && (row < H + HALF) && (col < W + HALF);
                if (cnt == N_TOTAL - 1) begin state <= S_DONE; end
                else begin
                    cnt <= cnt + 1;
                    if (col == W15 - 1) begin col <= 0; row <= row + 1; end else col <= col + 1;
                    if (is_img) cflat <= cflat + 1;
                    if (row >= HALF && col >= HALF) ccnt <= ccnt + 1;
                end
            end
            S_DONE: state <= S_DONE;
            endcase
        end
    end

    assign i_ready = (state == S_LOAD);
    assign o_data  = o_data_r;
    assign o_enh   = o_enh_r;
    assign o_valid = o_valid_r;
endmodule
