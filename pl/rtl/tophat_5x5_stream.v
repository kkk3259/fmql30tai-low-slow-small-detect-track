// tophat_5x5_stream.v —— 流式 5x5 Top-Hat（行缓存 + 流水线）
// TopHat = I - opening(I) = I - dilate(erode(I,5x5),5x5)
// ✅ 已验证：32x32 内部（r,c ∈ [5,27)）逐像素与 cv2.morphologyEx(MORPH_TOPHAT) 0 误差。
//    边界 2~3 像素回绕（win5 列回绕固有，检测可忽略：CFAR 31x31 本来丢 15 像素边界）。
// 结构：win5(腐蚀 min, PAD=255) → win5(膨胀 max, PAD=0) → 原始延迟 TD=4W+7 对齐。
// TD=4W+7：两级 win5 各 2W+3，加上 dilate 输入 valid 是寄存器多 1 拍（=4W+7）。
module tophat_5x5_stream #(
    parameter W = 32,
    parameter H = 32,
    parameter TD = 4 * W + 7   // 原始灰度延迟（对齐 opening）
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
    // TD 已改为参数（见模块声明），用于扫描对齐延迟

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

    // 寄存输出（与 win5 对齐，标准流式）
    reg [7:0] o_data_r;
    reg o_valid_r;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin o_data_r <= 8'd0; o_valid_r <= 1'b0; end
        else begin
            o_data_r  <= th;
            o_valid_r <= dilated_valid;
        end
    end
    assign o_data  = o_data_r;
    assign o_valid = o_valid_r;
endmodule
