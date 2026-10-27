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
    parameter MAX_CAND = 5
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
    output wire [17:0] dbg_px
);
    wire [7:0] th_data, cf_data, cf_enh;
    wire th_valid, cf_valid;
    wire cf_ready;   // CFAR 的 i_ready（只在图像列有效）

    tophat_5x5_stream #(.W(W), .H(H)) u_tophat (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid), .i_ready(i_ready),
        .o_data(th_data), .o_valid(th_valid), .o_ready(cf_ready)
    );
    cfar_threshold_stream #(.W(W), .H(H)) u_cfar (
        .clk(clk), .rst_n(rst_n),
        .i_data(th_data), .i_valid(th_valid), .i_ready(cf_ready),
        .o_data(cf_data), .o_enh(cf_enh), .o_valid(cf_valid), .o_ready(1'b1)
    );
    candidate_extract_stream #(.W(W), .H(H), .MAX_CAND(MAX_CAND)) u_cand (
        .clk(clk), .rst_n(rst_n),
        .i_bin(cf_data), .i_bin_valid(cf_valid),
        .i_enh(cf_enh), .i_enh_valid(cf_valid),
        .o_valid(o_valid), .o_data(o_data), .o_ready(o_ready),
        .dbg_state(dbg_state), .dbg_px(dbg_px)
    );
endmodule
