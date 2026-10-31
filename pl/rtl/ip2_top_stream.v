// ip2_top_stream.v —— IP2 流式顶层：Top-Hat(流式) -> CFAR(流式) -> 候选提取(流式)
// 数据流：灰度帧 -> Top-Hat(增强图) -> CFAR(二值图) -> CCL(候选 x/y/area/peak)
// 对齐：CFAR 在内部虚拟光栅（W+30 列）上插入 PAD 列/行，需要 1 拍 1 个虚拟位置，
//   所以 CFAR 的 i_ready 只在图像列上有效 —— 必须把反压一路传回来（否则会丢像素）：
//     tophat.o_ready <- cfar.i_ready ；顶层 i_ready <- tophat.i_ready
// CFAR 同时输出 o_enh（= 因果中心像素，即与 bin 同位置的增强图），
//   CCL 直接用 bin+enh（已对齐），无需外部延迟线。
module ip2_top_stream #(
    parameter W = 64,
    parameter H = 64,
    parameter MAX_CAND = 5,
    parameter SE = 5,           // Top-Hat 结构元边长（奇数）：默认 5
    parameter MODE = 0,         // 0=Top-Hat(亮目标) 1=Black-Hat(暗目标)
    parameter DENOISE = 0,      // 1=CCL 去孤立点（板级顶层打开）
    parameter K = 1,            // CFAR 系数（x > mean + K*sd + FLOOR）
    parameter FLOOR = 3         // CFAR 底噪
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] i_data,
    input  wire i_valid,
    output wire i_ready,
    output wire [7:0] o_data,
    output wire o_valid,
    input  wire o_ready,
    output wire [2:0]  dbg_state,
    output wire [17:0] dbg_px,
    // ---- 调试探针（上板定位用）：把内部 valid 引出来给上层计数 ----
    output wire dbg_th_valid,   // TopHat → CFAR
    output wire dbg_cf_valid,   // CFAR → CCL
    output wire dbg_cf_ready,   // CFAR 的 i_ready（= TopHat 的 o_ready）
    output wire dbg_ch_ready,   // 链路入口 ready（= TopHat i_ready）
    output wire [31:0] dbg_ccl_vcnt  // CCL 内部数到的 valid 数（与 dbg_cf_valid 对拍）
);
    wire [7:0] th_data, cf_data, cf_enh;
    wire th_valid, cf_valid;
    wire cf_ready;   // CFAR 的 i_ready（只在图像列有效）
    wire th_ready;   // TopHat 的 i_ready（= 链路入口 ready）

    assign dbg_th_valid = th_valid;
    assign dbg_cf_valid = cf_valid;
    assign dbg_cf_ready = cf_ready;
    assign dbg_ch_ready = th_ready;

    tophat_5x5_stream #(.W(W), .H(H), .SE(SE), .MODE(MODE)) u_tophat (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid), .i_ready(th_ready),
        .o_data(th_data), .o_valid(th_valid), .o_ready(cf_ready)
    );
    cfar_threshold_stream #(.W(W), .H(H), .K(K), .FLOOR(FLOOR)) u_cfar (
        .clk(clk), .rst_n(rst_n),
        .i_data(th_data), .i_valid(th_valid), .i_ready(cf_ready),
        .o_data(cf_data), .o_enh(cf_enh), .o_valid(cf_valid), .o_ready(1'b1)
    );
    candidate_extract_stream #(.W(W), .H(H), .MAX_CAND(MAX_CAND), .DENOISE(DENOISE)) u_cand (
        .clk(clk), .rst_n(rst_n),
        // CFAR 的 o_data 是 8 bit，CCL 的 i_bin 是 1 bit：显式取"非零"，
        // 避免隐式截断（旧写法直接接 8 bit，Verific 只报 warning，语义不明）。
        .i_bin(|cf_data), .i_bin_valid(cf_valid),
        .i_enh(cf_enh), .i_enh_valid(cf_valid),
        .o_valid(o_valid), .o_data(o_data), .o_ready(o_ready),
        .dbg_state(dbg_state), .dbg_px(dbg_px),
        .dbg_vcnt(dbg_ccl_vcnt)
    );

    // 顶层 i_ready 就是 TopHat 的 i_ready（反压直通）
    assign i_ready = th_ready;
endmodule
