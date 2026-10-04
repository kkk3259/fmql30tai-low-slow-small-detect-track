// tophat_5x5_stream.v —— 流式 5x5 Top-Hat（行缓存 + 流水线）
// TopHat = I - opening(I) = I - dilate(erode(I,5x5),5x5)
// ⚠️ 状态：WIP（未完成），依赖 win5.v（win5 有 1 像素偏差 + 边界回绕未修，本模块未验证通过）。
//
// 结构：win5(腐蚀 min, PAD=255) → win5(膨胀 max, PAD=0) → 原始延迟 TD=4W+4 对齐。
// 验证：待 win5 修好后，用 gen_ip2_stimulus.py 的 ref_tophat.hex 比对
//       （内部应与 cv2.morphologyEx 一致；PAD=255/0 匹配 OpenCV 形态学"中性边界"）。
module tophat_5x5_stream #(
    parameter W = 32,
    parameter H = 32
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
    localparam TD = 4 * W + 4;   // 两级 win5 总延迟 = 2 × 2W+2

    wire [7:0] eroded;
    wire eroded_valid;
    wire eroded_ready;
    win5 #(.W(W), .IS_MAX(0), .PAD(8'd255)) u_erode (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid), .i_ready(i_ready),
        .o_data(eroded), .o_valid(eroded_valid), .o_ready(eroded_ready)
    );

    wire [7:0] dilated;
    wire dilated_valid;
    win5 #(.W(W), .IS_MAX(1), .PAD(8'd0)) u_dilate (
        .clk(clk), .rst_n(rst_n),
        .i_data(eroded), .i_valid(eroded_valid), .i_ready(eroded_ready),
        .o_data(dilated), .o_valid(dilated_valid), .o_ready(o_ready)
    );

    // 原始灰度延迟（对齐 opening）
    reg [7:0] gd [0:TD];
    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i <= TD; i = i + 1) gd[i] <= 8'd0;
        end else if (i_valid && i_ready) begin
            gd[0] <= i_data;
            for (i = 1; i <= TD; i = i + 1) gd[i] <= gd[i-1];
        end
    end

    wire [7:0] gray_c = gd[TD];
    wire [7:0] th = (gray_c >= dilated) ? (gray_c - dilated) : 8'd0;

    assign o_data  = th;
    assign o_valid = dilated_valid;
endmodule
