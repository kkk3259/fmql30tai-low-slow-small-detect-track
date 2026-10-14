// cfar_threshold_stream.v —— 流式 CFAR 自适应阈值（滑动盒式滤波，综合友好）
//
// 【重构要点】替代全帧积分图（全帧 2D 数组 + 除法索引，综合器推不出 BRAM）。
//   滑动盒 O(1) 求和：
//     - delay[0..31W] 深度延迟线 → "离开窗口"像素（31 行上同列）
//     - col_sum[0..W-1] 列和数组（顺序访问，BRAM 可推断）→ 每列 31 行竖直和
//     - fifo[0..30] 31 项移位寄存器 → 水平窗口（最近 31 列）
//     - window_sum = new_colsum + sum(fifo[0..29])（组合逻辑，31 输入加法器）
//   因果窗口中心在 (r-15,c-15)，输出比全帧版偏移 15 行 15 列（验证时对齐）。
//
// 阈值：thr = mean + K×MAD + FLOOR，img > thr 判目标(255)。
// 三阶段：S_LOAD 存图 → S_MEAN 算 mean 存 mean_bram → S_MAD 算 MAD 并二值化。
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
    output wire [7:0] o_enh,    // 对齐的增强图（因果中心像素，与 o_data 同位置）
    output wire o_valid,
    input  wire o_ready
);
    localparam N = W * H;
    localparam CNT_W = $clog2(N + 1);
    localparam CW = $clog2(W + 1);
    localparam CH = $clog2(H + 1);
    localparam WIN_AREA = WIN * WIN;                 // 961
    localparam SUM_W = $clog2(WIN_AREA * 255) + 1;   // 盒和位宽
    localparam DELAY_D = WIN * W;                    // 31W 延迟线深度
    localparam CENTER_OFF = 15 * W + 15;             // 因果中心偏移（15 行 15 列）

    reg [7:0]  img_bram  [0:N-1];
    reg [7:0]  mean_bram [0:N-1];

    reg [7:0] delay [0:DELAY_D];
    reg [SUM_W-1:0] col_sum [0:W-1];
    reg [SUM_W-1:0] fifo [0:WIN-1];
    reg [CW-1:0] col;
    reg [CH-1:0] row;
    reg [CNT_W-1:0] cnt;

    reg [2:0] state;
    localparam S_LOAD = 0, S_MEAN = 1, S_MAD = 2, S_DONE = 3;

    integer i;

    // ---- 当前像素与均值 ----
    wire [7:0] cur_px   = img_bram[cnt];
    // 局部均值（abs_dev 用）：mean_bram 存的是未偏移的 mu(k)
    wire [7:0] mean_local  = mean_bram[cnt];
    // 中心均值（阈值用）：因果窗口中心 = cnt - CENTER_OFF
    wire [7:0] mean_center = mean_bram[(cnt >= CENTER_OFF) ? (cnt - CENTER_OFF) : 0];
    wire [7:0] abs_d = (cur_px >= mean_local) ? (cur_px - mean_local) : (mean_local - cur_px);
    // 当前被求和的像素：S_MEAN 用原图，S_MAD 用 |img-mean|
    wire [7:0] cur_val  = (state == S_MEAN) ? cur_px : abs_d;

    // ---- 滑动盒窗口和（组合逻辑）----
    // new_colsum = col_sum + cur_val - leaving（结果恒非负：leaving 是 col_sum 的一项）
    wire [SUM_W-1:0] new_colsum = col_sum[col] + {1'b0, cur_val} - {1'b0, delay[DELAY_D]};
    wire [SUM_W-1:0] window_sum = new_colsum + fifo[0] + fifo[1] + fifo[2] + fifo[3] + fifo[4] +
                                  fifo[5] + fifo[6] + fifo[7] + fifo[8] + fifo[9] + fifo[10] +
                                  fifo[11] + fifo[12] + fifo[13] + fifo[14] + fifo[15] + fifo[16] +
                                  fifo[17] + fifo[18] + fifo[19] + fifo[20] + fifo[21] + fifo[22] +
                                  fifo[23] + fifo[24] + fifo[25] + fifo[26] + fifo[27] + fifo[28] + fifo[29];

    // 裁剪窗口面积（因果窗口：有效行×有效列，1..961）
    wire [5:0] rw = (row < WIN - 1) ? (row + 6'd1) : WIN[5:0];
    wire [5:0] cw = (col < WIN - 1) ? (col + 6'd1) : WIN[5:0];
    wire [10:0] win_area_c = rw * cw;
    // 盒均值 / MAD（变量除法，综合时换倒数 LUT）
    wire [7:0] box_avg = window_sum / win_area_c;
    // 阈值：中心均值 + K×MAD + FLOOR
    wire [16:0] thr = {9'd0, mean_center} + K * {9'd0, box_avg} + FLOOR;
    // 中心像素（因果窗口中心，需延迟 CENTER_OFF 拍）
    wire [7:0] center_px = img_bram[(cnt >= CENTER_OFF) ? (cnt - CENTER_OFF) : 0];

    reg [7:0] o_data_r;
    reg [7:0] o_enh_r;
    reg o_valid_r;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i <= DELAY_D; i = i + 1) delay[i] <= 8'd0;
            for (i = 0; i < W; i = i + 1) col_sum[i] <= 0;
            for (i = 0; i < WIN; i = i + 1) fifo[i] <= 0;
            col <= 0; row <= 0; cnt <= 0; state <= S_LOAD;
            o_data_r <= 8'd0; o_enh_r <= 8'd0; o_valid_r <= 1'b0;
        end else begin
            o_valid_r <= 1'b0;
            case (state)
            S_LOAD: begin
                if (i_valid) begin
                    img_bram[cnt] <= i_data;
                    if (cnt == N - 1) begin state <= S_MEAN; cnt <= 0; col <= 0; row <= 0; end
                    else cnt <= cnt + 1;
                end
            end
            S_MEAN: begin
                // 滑动盒移位 + 列和更新
                delay[0] <= cur_px;
                for (i = 1; i <= DELAY_D; i = i + 1) delay[i] <= delay[i-1];
                col_sum[col] <= new_colsum;
                fifo[0] <= new_colsum;
                if (col == 0) begin
                    for (i = 1; i < WIN; i = i + 1) fifo[i] <= 0;  // 行首清负列
                end else begin
                    for (i = 1; i < WIN; i = i + 1) fifo[i] <= fifo[i-1];
                end
                if (cnt >= CENTER_OFF) mean_bram[cnt - CENTER_OFF] <= box_avg;  // 存未偏移 mu(k)
                if (cnt == N - 1) begin
                    state <= S_MAD; cnt <= 0; col <= 0; row <= 0;
                    // 切换 MAD 前清零滑动盒（改用 |px-mean| 重新累加）
                    for (i = 0; i <= DELAY_D; i = i + 1) delay[i] <= 8'd0;
                    for (i = 0; i < W; i = i + 1) col_sum[i] <= 0;
                    for (i = 0; i < WIN; i = i + 1) fifo[i] <= 0;
                end
                else begin
                    cnt <= cnt + 1;
                    if (col == W - 1) begin col <= 0; row <= row + 1; end else col <= col + 1;
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
                o_enh_r  <= center_px;   // 对齐的增强图（与二值图同位置）
                o_valid_r <= 1'b1;
                if (cnt == N - 1) begin state <= S_DONE; end
                else begin
                    cnt <= cnt + 1;
                    if (col == W - 1) begin col <= 0; row <= row + 1; end else col <= col + 1;
                end
            end
            S_DONE: state <= S_DONE;
            endcase
        end
    end

    // 仿真初始化：mean_bram 右下角（因果窗口算不到）置 0，避免 X 传播
    integer j;
    initial begin
        for (j = 0; j < N; j = j + 1) mean_bram[j] = 8'd0;
    end

    assign i_ready = (state == S_LOAD);
    assign o_data  = o_data_r;
    assign o_enh   = o_enh_r;
    assign o_valid = o_valid_r;
endmodule
