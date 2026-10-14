// ip2_top_stream.v —— IP2 流式顶层：Top-Hat(流式) -> CFAR(流式) -> 候选提取(流式)
// 数据流：灰度帧 -> Top-Hat(增强图) -> CFAR(二值图) -> CCL(候选 x/y/area/peak)
// 对齐：CFAR 的 bin 输出比 enh 对应位置晚 CENTER_OFF=15W+15 拍（因果窗口中心偏移），
//       故 enh 送 CCL 前延迟 CENTER_OFF 拍，使 bin/enh 逐像素对齐。
// CCL 内部用独立 bin/enh 计数器分别加载（bin 比 enh 晚 2N 拍到达），无需外部帧对齐。
module ip2_top_stream #(
    parameter W = 64,
    parameter H = 64,
    parameter MAX_CAND = 5
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] i_data,
    input  wire i_valid,
    output wire [7:0] o_data,
    output wire o_valid,
    input  wire o_ready
);
    localparam CENTER_OFF = 15 * W + 15;

    wire [7:0] th_data, cf_data;
    wire th_valid, cf_valid;

    tophat_5x5_stream #(.W(W), .H(H)) u_tophat (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid),
        .o_data(th_data), .o_valid(th_valid), .o_ready(1'b1)
    );
    cfar_threshold_stream #(.W(W), .H(H)) u_cfar (
        .clk(clk), .rst_n(rst_n),
        .i_data(th_data), .i_valid(th_valid),
        .o_data(cf_data), .o_valid(cf_valid), .o_ready(1'b1)
    );

    // enh 延迟 CENTER_OFF 拍对齐 bin
    reg [7:0] enh_shift [0:CENTER_OFF-1];
    reg enh_valid_shift [0:CENTER_OFF-1];
    integer k;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (k = 0; k < CENTER_OFF; k = k + 1) begin enh_shift[k] <= 8'd0; enh_valid_shift[k] <= 1'b0; end
        end else begin
            enh_shift[0] <= th_data;
            enh_valid_shift[0] <= th_valid;
            for (k = 1; k < CENTER_OFF; k = k + 1) begin
                enh_shift[k] <= enh_shift[k-1];
                enh_valid_shift[k] <= enh_valid_shift[k-1];
            end
        end
    end
    wire [7:0] th_delayed = enh_shift[CENTER_OFF-1];
    wire th_valid_delayed = enh_valid_shift[CENTER_OFF-1];

    candidate_extract_stream #(.W(W), .H(H), .MAX_CAND(MAX_CAND)) u_cand (
        .clk(clk), .rst_n(rst_n),
        .i_bin(cf_data), .i_bin_valid(cf_valid),
        .i_enh(th_delayed), .i_enh_valid(th_valid_delayed),
        .o_valid(o_valid), .o_data(o_data), .o_ready(o_ready)
    );
endmodule
