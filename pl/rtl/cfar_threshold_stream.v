// cfar_threshold_stream.v —— 流式 CFAR 自适应阈值（单趟、真实标准差）
// 判决：thr = mean + K×std + FLOOR，img > thr 判目标(255)。
//
// 【为什么从 MAD 改成 std（2026-10-23）】
//   PS 侧基线 detect_v1.py 用的是真实标准差：
//       mu  = boxFilter(img,  (31,31))
//       mu2 = boxFilter(img², (31,31))
//       sd  = sqrt(mu2 - mu²)
//       thr = mu + k·sd + floor,  k = 4.0,  floor = 3.0
//   早期硬件用 MAD 近似（thr = mean + 5·MAD + 3），与 Python 差一个 1.4826 常数，
//   候选表永远对不上 → 现按真实 std 重写。
//
// 【不开方器的等价判决（关键，改这里前先看懂）】
//   记 A = 裁剪后窗口面积、S1 = Σx、S2 = Σx²：
//       mu = S1/A,   sd = sqrt(A·S2 - S1²)/A
//       x > mu + k·sd + floor
//     ⟺  L > k·sqrt(A·S2 - S1²),       其中 L = x·A - S1 - floor·A
//     ⟺  (L > 0) 且 L² > k²·(A·S2 - S1²)     ← 两边都非负才能平方
//   位宽：L ≤ 255×961 = 245,055（18 bit）；L² ≤ 6.01e10（36 bit）；
//        A·S2 - S1² ≤ 961×62,489,025 ≈ 6.01e10（36 bit）；×k²=16 ≤ 9.6e11（40 bit）。
//   所以硬件上只需要 4 个真乘法器（8×8 平方、8×11、11×26、18×18），
//   不需要除法/开方；k²=16 与 WMAX 都是 2 的幂，综合成移位。
//
// 【因果对齐（单趟，两个盒共用同一个窗口）】
//   虚拟光栅 W15×H15：图像占 row<H、col<W，其余位置是 PAD（补 0）。
//     - 盒1 输入 cur_px、盒2 输入 cur_px²，共用同一套列和与环形延迟线，
//       因此同一拍得到的 S1、S2 描述的是**同一个** 31×31 窗口；
//     - 虚拟位置 t 的窗口 = 行 [r-30,r] × 列 [c-30,c]，中心 u = (r-15, c-15)；
//     - 中心像素 x(u) 由 rb2 取回（延迟 CENTER_OFF = 15 行 + 15 列 = 15·W15+15）；
//     - 窗口面积 A 按 u 裁剪：crow = row-15、ccol = col-15，
//       与 PS 侧 max/min 裁剪完全一致（上/下/左/右都对齐，无 1 列偏移）。
//   输出行 row∈[15,H+15)、列 col∈[15,W+15) 恰好 N=H×W 个；之后 state→S_DONE。
//
// 【存储（640×360 → W15=655, H15=375, DLY=20,305, CENTER_OFF=9,840）】
//     rb1 20,306×8（延迟 DLY，供盒1 移出值）
//     rb2  9,841×8（延迟 CENTER_OFF，供中心像素 x(u)）
//     rb3 20,306×16（平方流延迟 DLY，供盒2 移出值）
//     cs1   655×13、cs2 655×21
//   合计 ≈ 566 Kbit（原两趟全帧方案 7.5 Mbit，折合 16 万 LUT，装不进器件）。
//
// 【RAM 写法约束（Verific）】写必须在独立 always 块里、不能写进状态机 case 分支，
//   否则报 ELAB-E-353 "Failed to dissolve the memory into bits ... too large"。
//   环形线统一“写 wp、读 (wp+1) mod DEPTH” → 延迟 = DEPTH-1，全数组都是 1 写 1 读。
module cfar_threshold_stream #(
    parameter W = 64,
    parameter H = 64,
    parameter WIN = 31,
    parameter K = 4,
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
    localparam N     = W * H;
    localparam HALF  = WIN / 2;                     // 15
    localparam W15   = W + HALF;                    // 虚拟列宽
    localparam H15   = H + HALF;                    // 虚拟行高
    localparam N_EXT = H15 * W15;                   // 虚拟总位置数
    localparam DLY   = WIN * W15;                   // 盒竖直延迟：31 行
    localparam DEP_A = DLY + 1;                     // 读 (wp+1) → 延迟 DLY
    localparam CENTER_OFF = HALF * W15 + HALF;      // 15 行 + 15 列
    localparam DEP_B = CENTER_OFF + 1;              // 读 (wp+1) → 延迟 CENTER_OFF

    localparam CNT_W = $clog2(N_EXT + 1);
    localparam CW    = $clog2(W15 + 1);
    localparam CH    = $clog2(H15 + 1);
    localparam PA    = $clog2(DEP_A);               // rb1/rb3 指针位宽
    localparam PB    = $clog2(DEP_B);               // rb2 指针位宽

    localparam A_W   = 11;                          // 面积 ≤ 961
    localparam CS1_W = $clog2(WIN * 255) + 1;               // 13  列和（灰阶）
    localparam WS1_W = $clog2(WIN * WIN * 255) + 1;         // 18  窗口和（灰阶）
    localparam CS2_W = $clog2(WIN * 255 * 255) + 1;         // 21  列和（平方）
    localparam WS2_W = $clog2(WIN * WIN * 255 * 255) + 1;   // 26  窗口和（平方）
    localparam KSQ   = K * K;

    reg [CW-1:0] col;
    reg [CH-1:0] row;
    reg [CNT_W-1:0] cnt;                 // 虚拟位置计数
    reg [1:0] state;
    localparam S_RUN = 0, S_DONE = 1;

    integer i;

    // ---- 当前虚拟位置 ----
    wire is_img = (row < H) && (col < W);
    wire [7:0] cur_px  = is_img ? i_data : 8'd0;
    wire [15:0] sq_px  = cur_px * cur_px;

    // 图像位置需要上游给数；PAD 位置自行推进
    wire adv = (state == S_RUN) && (is_img ? i_valid : 1'b1);

    // ---- 三条环形延迟线（全 1 写 1 读）----
    reg [7:0]  rb1 [0:DEP_A-1];   // cur_px   → 盒1 移出值（延迟 DLY）
    reg [15:0] rb3 [0:DEP_A-1];   // cur_px²  → 盒2 移出值（延迟 DLY）
    reg [7:0]  rb2 [0:DEP_B-1];   // cur_px   → 中心像素 x(u)（延迟 CENTER_OFF）

    reg [PA-1:0] wpa, filla;
    reg [PB-1:0] wpb, fillb;

    wire [PA-1:0] rpa = (wpa == DEP_A[PA-1:0] - 1'b1) ? {PA{1'b0}} : (wpa + 1'b1);
    wire [PB-1:0] rpb = (wpb == DEP_B[PB-1:0] - 1'b1) ? {PB{1'b0}} : (wpb + 1'b1);
    wire full_a = (filla >= DLY[PA-1:0]);            // 延迟 DLY 有效
    wire full_b = (fillb >= CENTER_OFF[PB-1:0]);     // 延迟 CENTER_OFF 有效

    wire [7:0]  d1_old = full_a ? rb1[rpa] : 8'd0;   // cur_px(r-31, c)
    wire [15:0] d2_old = full_a ? rb3[rpa] : 16'd0;  // 平方流(r-31, c)
    wire [7:0]  x_mid  = full_b ? rb2[rpb] : 8'd0;   // x(r-15, c-15) = 窗口中心

    // ---- 列和数组（1 写 1 读；不复位，row!=0 门控首次读为 0）----
    reg [CS1_W-1:0] cs1 [0:W15-1];
    reg [CS2_W-1:0] cs2 [0:W15-1];

    wire [CS1_W-1:0] cs1_rd = (row != 0) ? cs1[col] : {CS1_W{1'b0}};
    wire [CS2_W-1:0] cs2_rd = (row != 0) ? cs2[col] : {CS2_W{1'b0}};
    wire [CS1_W-1:0] ncs1 = cs1_rd + {5'd0, cur_px}  - {5'd0, d1_old};
    wire [CS2_W-1:0] ncs2 = cs2_rd + {5'd0, sq_px}   - {5'd0, d2_old};

    // ---- 水平 31 项（每项是一列的竖直和）----
    reg [CS1_W-1:0] f1 [0:WIN-1];
    reg [CS2_W-1:0] f2 [0:WIN-1];

    wire [WS1_W-1:0] ws1 = ncs1
        + f1[0]  + f1[1]  + f1[2]  + f1[3]  + f1[4]  + f1[5]  + f1[6]  + f1[7]
        + f1[8]  + f1[9]  + f1[10] + f1[11] + f1[12] + f1[13] + f1[14] + f1[15]
        + f1[16] + f1[17] + f1[18] + f1[19] + f1[20] + f1[21] + f1[22] + f1[23]
        + f1[24] + f1[25] + f1[26] + f1[27] + f1[28] + f1[29];
    wire [WS2_W-1:0] ws2 = ncs2
        + f2[0]  + f2[1]  + f2[2]  + f2[3]  + f2[4]  + f2[5]  + f2[6]  + f2[7]
        + f2[8]  + f2[9]  + f2[10] + f2[11] + f2[12] + f2[13] + f2[14] + f2[15]
        + f2[16] + f2[17] + f2[18] + f2[19] + f2[20] + f2[21] + f2[22] + f2[23]
        + f2[24] + f2[25] + f2[26] + f2[27] + f2[28] + f2[29];

    // ---- 裁剪面积 A（按中心 u = (row-15, col-15) 裁剪，与 PS 侧 max/min 一致）----
    wire [CH-1:0] cr = row - HALF;
    wire [CW-1:0] cc = col - HALF;
    wire [5:0] cnt_r = (cr < HALF) ? (cr + HALF + 1)
                     : ((cr >= H - HALF) ? (H + HALF - cr) : WIN[5:0]);
    wire [5:0] cnt_c = (cc < HALF) ? (cc + HALF + 1)
                     : ((cc >= W - HALF) ? (W + HALF - cc) : WIN[5:0]);
    wire [11:0] area_raw = cnt_r * cnt_c;
    wire [A_W-1:0] area_c = (area_raw == 12'd0) ? 11'd1 : area_raw[A_W-1:0];

    // ---- 判决：(x·A - S1 - FLOOR·A)² > K²·(A·S2 - S1²) ----
    wire [19:0] xa   = {12'd0, x_mid} * area_c;      // x·A       ≤ 245,055
    wire [19:0] fa   = FLOOR * area_c;               // FLOOR·A   ≤ 2,883
    wire [19:0] l_bound = {2'd0, ws1} + fa;          // S1 + FLOOR·A
    wire        l_pos  = (xa > l_bound);             // L > 0
    wire [19:0] l_mag  = l_pos ? (xa - l_bound) : 20'd0;
    wire [37:0] l_sq   = l_mag * l_mag;              // L²       ≤ 6.01e10

    wire [36:0] a_s2   = area_c * ws2;               // A·S2     ≤ 6.01e10
    wire [35:0] s1_sq  = ws1 * ws1;                  // S1²
    wire [36:0] var_n  = (a_s2 >= {1'b0, s1_sq}) ? (a_s2 - {1'b0, s1_sq}) : 37'd0;
    wire [40:0] lim    = var_n * KSQ;                // K²·(A·S2 - S1²)

    wire detect = l_pos && ({3'd0, l_sq} > lim);

    // 输出位置 u=(row-15,col-15)：row∈[15,H+15)、col∈[15,W+15) 恰好 H×W 个
    wire out_gate = (row >= HALF) && (col >= HALF) &&
                    (row < H + HALF) && (col < W + HALF);

    reg [7:0] o_data_r;
    reg [7:0] o_enh_r;
    reg o_valid_r;

    // ---- 环形线写块（独立 always，供综合器推断 RAM）----
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wpa <= 0; filla <= 0;
        end else if (adv) begin
            rb1[wpa] <= cur_px;
            rb3[wpa] <= sq_px;
            if (wpa == DEP_A[PA-1:0] - 1'b1) wpa <= {PA{1'b0}};
            else                             wpa <= wpa + 1'b1;
            if (filla < DEP_A[PA-1:0]) filla <= filla + 1'b1;
        end
    end
    // 中心像素延迟线
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wpb <= 0; fillb <= 0;
        end else if (adv) begin
            rb2[wpb] <= cur_px;
            if (wpb == DEP_B[PB-1:0] - 1'b1) wpb <= {PB{1'b0}};
            else                             wpb <= wpb + 1'b1;
            if (fillb < DEP_B[PB-1:0]) fillb <= fillb + 1'b1;
        end
    end
    // 列和数组（同址读旧值 + 写；不复位）
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // 无复位（RAM）
        end else if (adv) begin
            cs1[col] <= ncs1;
            cs2[col] <= ncs2;
        end
    end

    // ---- 状态机：fifo 移位、坐标推进、输出寄存 ----
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i < WIN; i = i + 1) begin f1[i] <= 0; f2[i] <= 0; end
            col <= 0; row <= 0; cnt <= 0; state <= S_RUN;
            o_data_r <= 8'd0; o_enh_r <= 8'd0; o_valid_r <= 1'b0;
        end else begin
            o_valid_r <= 1'b0;
            if (adv) begin
                f1[0] <= ncs1;
                f2[0] <= ncs2;
                if (col == 0) begin
                    for (i = 1; i < WIN; i = i + 1) begin f1[i] <= 0; f2[i] <= 0; end
                end else begin
                    for (i = 1; i < WIN; i = i + 1) begin f1[i] <= f1[i-1]; f2[i] <= f2[i-1]; end
                end

                o_data_r  <= detect ? 8'd255 : 8'd0;
                o_enh_r   <= x_mid;
                o_valid_r <= out_gate;

                if (cnt == N_EXT - 1) state <= S_DONE;
                else begin
                    cnt <= cnt + 1;
                    if (col == W15 - 1) begin col <= 0; row <= row + 1; end
                    else                     col <= col + 1;
                end
            end
            if (state == S_DONE) o_valid_r <= 1'b0;
        end
    end

    assign i_ready = (state == S_RUN) && is_img;
    assign o_data  = o_data_r;
    assign o_enh   = o_enh_r;
    assign o_valid = o_valid_r;
endmodule
