// cfar_threshold_stream.v —— 流式 CFAR 自适应阈值（融合单趟：均值盒 + MAD 盒并行）
// 阈值：thr = mean + K×MAD + FLOOR，img > thr 判目标(255)。
//
// 【2026-10 重构：两趟全帧 → 单趟流水】
//   原实现：S_MEAN 整帧算 mean 存 mean_bram，S_MAD 再整帧算 |x-mean| 的均值，
//   需要 img_bram/mean_bram 各 N×8（640×360 时 3.7 Mbit），只能落成查找表 RAM，
//   综合后 LUTRAM 折合 16 万 LUT，装不进器件。
//
// 【因果对齐推导（关键，改这里前先看懂）】
//   记 CENTER_OFF = 15 行 + 15 列的虚拟步偏移（= 15*W30+15），虚拟位置 t 上的
//   盒1 输出 = 以 (t - CENTER_OFF) 为中心的 31×31 均值；把"像素搬到当前拍"：
//     diff(t) = |x(t - CENTER_OFF) - mean(t)|        ← x 由 dbuf1 第二读址取回
//   于是盒2 在 t 的 31×31 窗口覆盖的像素是 [(t-2*CENTER_OFF) ± 15]，
//   即盒2 的输出 = mad(C)，C = t - 2*CENTER_OFF（比盒1 的中心再低 15 行/15 列）。
//   ⇒ **两个盒的裁剪除数不同**：
//     area1 = clip_cnt(row-15)*clip_cnt(col-15)   → 盒1（mean）
//     area2 = clip_cnt(row-30)*clip_cnt(col-30)   → 盒2（MAD）
//   输出：位置 t 对应像素 C，o_enh = x(C)（dbuf1 第三读址，延迟 2*CENTER_OFF），
//        mean(C) = mbuf（mean 流延迟 CENTER_OFF，深度 CENTER_OFF+1），
//        thr = mean(C) + K*mad(C) + FLOOR，o_data = (x(C) > thr) ? 255 : 0。
//   虚拟光栅仍是 PAD 补边：行 0..H+29、列 0..W+29（W30×H30），尾部 PAD 行/列
//   用来把流水线里最后几行/列的像素冲出。
//
//   存储（640×360 → W30=670, H30=390, CENTER_OFF=10065, DLY=20770）：
//     dbuf1 20771×8（1写3读）、dbuf2 20771×8（1写1读）、mbuf 10066×8（1写1读）
//                   合计 ≈ 516 Kbit（原 7.5 Mbit ≈ 9K LUT）
//
// 【RAM 写法约束（Verific）】写必须在独立 always 块、不能写进状态机 case 分支，
//   否则报 ELAB-E-353 "Failed to dissolve the memory into bits ... too large"。
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
    localparam HALF = WIN / 2;                      // 15
    localparam W30 = W + 2 * HALF;                  // 虚拟列宽 W+30
    localparam H30 = H + 2 * HALF;                  // 虚拟行高 H+30
    localparam N_EXT = H30 * W30;                   // 虚拟总位置数
    localparam CENTER_OFF = HALF * W30 + HALF;      // 虚拟步偏移：15 行 + 15 列
    localparam CNT_W = $clog2(N_EXT + 1);
    localparam CW = $clog2(W30 + 1);
    localparam CH = $clog2(H30 + 1);
    localparam WIN_AREA = WIN * WIN;                // 961
    localparam SUM_W = $clog2(WIN_AREA * 255) + 1;  // 盒和位宽
    localparam DLY = WIN * W30;                     // 盒竖直延迟：31 行
    localparam DDEPTH = DLY + 1;                    // dbuf 环形深度
    localparam MDEPTH = CENTER_OFF + 1;             // mbuf 环形深度
    localparam OUTD = 2 * CENTER_OFF;               // x(C) 的延迟
    localparam QOFF = DDEPTH - CENTER_OFF;          // 取 x(t-CENTER_OFF) 的索引补偿
    localparam COFF = DDEPTH - OUTD;                // 取 x(C) 的索引补偿

    // ---- 三条环形延迟线 ----
    reg [7:0] dbuf1 [0:DDEPTH-1];   // cur_px：盒1 竖直和 / diff 对齐 / 中心像素
    reg [7:0] dbuf2 [0:DDEPTH-1];   // diff  ：盒2 竖直和
    reg [7:0] mbuf  [0:MDEPTH-1];   // mean  ：供 mean(C)

    // ---- 两组滑动盒 ----
    reg [SUM_W-1:0] cs1 [0:W30-1];
    reg [SUM_W-1:0] cs2 [0:W30-1];
    reg [SUM_W-1:0] f1  [0:WIN-1];  // 水平 31 项移位（寄存器）
    reg [SUM_W-1:0] f2  [0:WIN-1];

    reg [CNT_W-1:0] dptr;    // dbuf1/dbuf2 写指针 0..DLY
    reg [CNT_W-1:0] dfill;   // 已填拍数，饱和于 DDEPTH
    reg [CNT_W-1:0] mptr;    // mbuf 写指针 0..CENTER_OFF
    reg [CNT_W-1:0] mfill;   // 已填拍数，饱和于 MDEPTH

    reg [CW-1:0] col;
    reg [CH-1:0] row;
    reg [CNT_W-1:0] cnt;     // 虚拟位置计数

    reg [1:0] state;
    localparam S_RUN = 0, S_DONE = 1;

    integer i;

    // ---- 当前虚拟位置 ----
    wire is_img = (row < H) && (col < W);
    wire [7:0] cur_px = is_img ? i_data : 8'd0;

    // 图像位置需要上游给数；PAD 位置（含尾部补边）自行推进
    wire adv = (state == S_RUN) && (is_img ? i_valid : 1'b1);

    // ---- 环形缓冲读址 ----
    wire dfill_late = (dfill > DLY);                 // 盒竖直延迟已满
    wire dfill_mid  = (dfill >= CENTER_OFF);         // x(t-CENTER_OFF) 可用
    wire dfill_out  = (dfill >= OUTD);               // x(C) 可用
    wire mfill_mid  = (mfill > CENTER_OFF);          // mean(C) 可用

    wire [CNT_W-1:0] qidx = (dptr >= CENTER_OFF) ? (dptr - CENTER_OFF) : (dptr + QOFF);
    wire [CNT_W-1:0] cidx = (dptr >= OUTD)       ? (dptr - OUTD)       : (dptr + COFF);
    wire [CNT_W-1:0] mrp  = (mptr == CENTER_OFF) ? {CNT_W{1'b0}}       : (mptr + 1'b1);

    wire [7:0] d1_old  = dfill_late ? dbuf1[dptr] : 8'd0;
    wire [7:0] x_mid   = dfill_mid  ? dbuf1[qidx] : 8'd0;   // x(t-CENTER_OFF)
    wire [7:0] x_out   = dfill_out  ? dbuf1[cidx] : 8'd0;   // x(C)，C = t-2*CENTER_OFF
    wire [7:0] d2_old  = dfill_late ? dbuf2[dptr] : 8'd0;
    wire [7:0] mean_C  = mfill_mid  ? mbuf[mrp]   : 8'd0;   // mean(C)

    // ---- 盒1：cur_px → mean(中心 = t - CENTER_OFF) ----
    // 列和数组不参与复位（要落成 RAM），用 row!=0 做"本趟尚未写入"的零值门控：
    // 虚拟第 0 行每个列都是首次读，读到的必须是 0（等价原版 col_sum 复位为 0）。
    wire [SUM_W-1:0] cs1_rd = (row != 0) ? cs1[col] : {SUM_W{1'b0}};
    wire [SUM_W-1:0] ncs1 = cs1_rd + {1'b0, cur_px} - {1'b0, d1_old};
    wire [SUM_W-1:0] ws1 = ncs1 + f1[0] + f1[1] + f1[2] + f1[3] + f1[4] +
                           f1[5] + f1[6] + f1[7] + f1[8] + f1[9] + f1[10] +
                           f1[11] + f1[12] + f1[13] + f1[14] + f1[15] + f1[16] +
                           f1[17] + f1[18] + f1[19] + f1[20] + f1[21] + f1[22] +
                           f1[23] + f1[24] + f1[25] + f1[26] + f1[27] + f1[28] + f1[29];

    // ---- 裁剪面积（两个盒中心不同，必须分开算）----
    wire [CH-1:0] cr1 = row - HALF;
    wire [CW-1:0] cc1 = col - HALF;
    wire [5:0] cnt_r1 = (cr1 < HALF) ? (cr1 + HALF + 1) : ((cr1 >= H - HALF) ? (H + HALF - cr1) : WIN[5:0]);
    wire [5:0] cnt_c1 = (cc1 < HALF) ? (cc1 + HALF + 1) : ((cc1 >= W - HALF) ? (W + HALF - cc1) : WIN[5:0]);
    wire [11:0] area1_raw = cnt_r1 * cnt_c1;
    wire [10:0] area1 = (area1_raw == 12'd0) ? 11'd1 : area1_raw[10:0];

    wire [CH-1:0] cr2 = row - 2 * HALF;
    wire [CW-1:0] cc2 = col - 2 * HALF;
    wire [5:0] cnt_r2 = (cr2 < HALF) ? (cr2 + HALF + 1) : ((cr2 >= H - HALF) ? (H + HALF - cr2) : WIN[5:0]);
    wire [5:0] cnt_c2 = (cc2 < HALF) ? (cc2 + HALF + 1) : ((cc2 >= W - HALF) ? (W + HALF - cc2) : WIN[5:0]);
    wire [11:0] area2_raw = cnt_r2 * cnt_c2;
    wire [10:0] area2 = (area2_raw == 12'd0) ? 11'd1 : area2_raw[10:0];

    wire [7:0] mean_t = ws1 / area1;                            // mean(t-CENTER_OFF)
    // diff 的像素 p = t-CENTER_OFF；只有 p 落在图像内才是有意义的 abs 偏差，
    // 否则（PAD 位置：窗口被裁成"角落均值"、x 为 0）会产生虚假大偏差污染 MAD 盒。
    wire p_in = (row >= HALF) && (col >= HALF) &&
                (row < H + HALF) && (col < W + HALF);
    wire [7:0] abs_d = (dfill_mid && p_in)
                     ? ((x_mid >= mean_t) ? (x_mid - mean_t) : (mean_t - x_mid))
                     : 8'd0;

    // ---- 盒2：diff → mad(C)，C = (row-30, col-30) ----
    wire [SUM_W-1:0] cs2_rd = (row != 0) ? cs2[col] : {SUM_W{1'b0}};
    wire [SUM_W-1:0] ncs2 = cs2_rd + {1'b0, abs_d} - {1'b0, d2_old};
    wire [SUM_W-1:0] ws2 = ncs2 + f2[0] + f2[1] + f2[2] + f2[3] + f2[4] +
                           f2[5] + f2[6] + f2[7] + f2[8] + f2[9] + f2[10] +
                           f2[11] + f2[12] + f2[13] + f2[14] + f2[15] + f2[16] +
                           f2[17] + f2[18] + f2[19] + f2[20] + f2[21] + f2[22] +
                           f2[23] + f2[24] + f2[25] + f2[26] + f2[27] + f2[28] + f2[29];
    wire [7:0] mad = ws2 / area2;

    wire [16:0] thr = {9'd0, mean_C} + K * {9'd0, mad} + FLOOR;
    // 输出位置 C=(row-30,col-30)：行 row∈[30,H+29]、列 col∈[30,W+29] 恰好 H×W 个
    wire out_gate = (row >= 2 * HALF) && (col >= 2 * HALF) &&
                    (row < H + 2 * HALF) && (col < W + 2 * HALF);

    reg [7:0] o_data_r;
    reg [7:0] o_enh_r;
    reg o_valid_r;

    // ---- RAM 独立写块（1写 + 多读，供综合器推断 RAM）----
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            dptr <= 0; dfill <= 0;
        end else if (adv) begin
            dbuf1[dptr] <= cur_px;
            dbuf2[dptr] <= abs_d;
            if (dptr == DLY) dptr <= 0;
            else             dptr <= dptr + 1;
            if (dfill <= DLY) dfill <= dfill + 1;
        end
    end
    // mean 延迟线（独立指针）
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mptr <= 0; mfill <= 0;
        end else if (adv) begin
            mbuf[mptr] <= mean_t;
            if (mptr == CENTER_OFF) mptr <= 0;
            else                    mptr <= mptr + 1;
            if (mfill < MDEPTH) mfill <= mfill + 1;
        end
    end
    // 列和数组（同址读旧值 + 写；不复位，靠 row!=0 门控首次读为 0）
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // 无复位（RAM）
        end else if (adv) begin
            cs1[col] <= ncs1;
            cs2[col] <= ncs2;
        end
    end

    // ---- 状态机：只做 fifo 移位、坐标推进、输出寄存 ----
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

                o_data_r  <= (x_out > thr[7:0]) ? 8'd255 : 8'd0;
                o_enh_r   <= x_out;
                o_valid_r <= out_gate;

                if (cnt == N_EXT - 1) state <= S_DONE;
                else begin
                    cnt <= cnt + 1;
                    if (col == W30 - 1) begin col <= 0; row <= row + 1; end
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
