// preproc_axis.v —— IP1 图像预处理
// 功能：RGB -> 灰度(BT.601) -> 2x 降采样 -> 3x3 高斯去噪
// 输入：W_IN x H_IN 的 RGB 像素流（行优先，i_valid 每周期一个像素）
// 输出：(W_IN/2) x (H_IN/2) 的灰度图（3x3 高斯后）
// 定点约定：gray = (77R+150G+29B+128)>>8 ；gauss = (加权和+8)>>4（均四舍五入，对齐 OpenCV cvRound）
module preproc_axis #(
    parameter W_IN = 32,
    parameter H_IN = 32
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] i_r,
    input  wire [7:0] i_g,
    input  wire [7:0] i_b,
    input  wire i_valid,
    output reg  [7:0] o_data,
    output reg  o_valid,
    input  wire o_ready
);
    localparam W_OUT = W_IN / 2;          // 16
    localparam H_OUT = H_IN / 2;          // 16
    localparam IN_TOTAL  = W_IN * H_IN;   // 1024
    localparam OUT_TOTAL = W_OUT * H_OUT; // 256

    // 降采样后的灰度图缓存（16x16）
    reg [7:0] gray_mem [0:H_OUT-1][0:W_OUT-1];

    reg [9:0] in_cnt;    // 0..1023
    reg [7:0] out_cnt;   // 0..255
    reg [1:0] state;
    localparam S_IN = 2'd0, S_OUT = 2'd1, S_DONE = 2'd2;

    // ---- 输入阶段：灰度化 + 降采样 ----
    wire [4:0] in_row = in_cnt[9:5];   // 0..31
    wire [4:0] in_col = in_cnt[4:0];   // 0..31
    wire [3:0] ds_row = in_row[4:1];   // row>>1
    wire [3:0] ds_col = in_col[4:1];   // col>>1
    // 灰度在写入时现算（不搞连续赋值，避免首拍竞态）

    // ---- 输出阶段：3x3 高斯（边界 clamp）----
    wire [3:0] o_row = out_cnt[7:4];   // 0..15
    wire [3:0] o_col = out_cnt[3:0];   // 0..15
    wire [3:0] r0 = (o_row == 4'd0) ? 4'd0 : o_row - 4'd1;
    wire [3:0] r2 = (o_row == H_OUT-1) ? o_row : o_row + 4'd1;
    wire [3:0] c0 = (o_col == 4'd0) ? 4'd0 : o_col - 4'd1;
    wire [3:0] c2 = (o_col == W_OUT-1) ? o_col : o_col + 4'd1;
    wire [7:0] p00 = gray_mem[r0][c0];
    wire [7:0] p01 = gray_mem[r0][o_col];
    wire [7:0] p02 = gray_mem[r0][c2];
    wire [7:0] p10 = gray_mem[o_row][c0];
    wire [7:0] p11 = gray_mem[o_row][o_col];
    wire [7:0] p12 = gray_mem[o_row][c2];
    wire [7:0] p20 = gray_mem[r2][c0];
    wire [7:0] p21 = gray_mem[r2][o_col];
    wire [7:0] p22 = gray_mem[r2][c2];
    wire [11:0] gsum  = p00 + (p01 << 1) + p02 + (p10 << 1) + (p11 << 2) + (p12 << 1)
                      + p20 + (p21 << 1) + p22;
    wire [7:0]  gauss = (gsum + 12'd8) >> 4;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            in_cnt  <= 10'd0;
            out_cnt <= 8'd0;
            state   <= S_IN;
            o_data  <= 8'd0;
            o_valid <= 1'b0;
        end else begin
            case (state)
                S_IN: begin
                    if (i_valid) begin
                        if (in_row[0] == 1'b0 && in_col[0] == 1'b0)
                            gray_mem[ds_row][ds_col] <= (i_r*8'd77 + i_g*8'd150 + i_b*8'd29 + 16'd128) >> 8;
                        in_cnt <= in_cnt + 10'd1;
                        if (in_cnt == IN_TOTAL - 1) begin
                            state   <= S_OUT;
                            out_cnt <= 8'd0;
                        end
                    end
                end
                S_OUT: begin
                    o_data  <= gauss;
                    o_valid <= 1'b1;
                    if (o_ready) begin
                        if (out_cnt == OUT_TOTAL - 1)
                            state <= S_DONE;
                        else
                            out_cnt <= out_cnt + 8'd1;
                    end
                end
                S_DONE: begin
                    o_valid <= 1'b0;
                end
            endcase
        end
    end
endmodule
