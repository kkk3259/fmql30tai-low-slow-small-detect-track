// ip2_top.v —— IP2 顶层：Top-Hat -> CFAR -> 候选提取（64x64 整合）
module ip2_top #(
    parameter W = 64,
    parameter H = 64
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] i_data,
    input  wire i_valid,
    output wire [7:0] o_data,
    output wire o_valid,
    input  wire o_ready
);
    wire [7:0] th_data, cf_data;
    wire th_valid, cf_valid;

    tophat_5x5 #(.W(W), .H(H)) u_tophat (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid),
        .o_data(th_data), .o_valid(th_valid), .o_ready(1'b1)
    );
    cfar_threshold #(.W(W), .H(H)) u_cfar (
        .clk(clk), .rst_n(rst_n),
        .i_data(th_data), .i_valid(th_valid),
        .o_data(cf_data), .o_valid(cf_valid), .o_ready(1'b1)
    );
    candidate_extract #(.W(W), .H(H)) u_cand (
        .clk(clk), .rst_n(rst_n),
        .i_data(cf_data), .i_valid(cf_valid),
        .o_data(o_data), .o_valid(o_valid), .o_ready(o_ready)
    );
endmodule
