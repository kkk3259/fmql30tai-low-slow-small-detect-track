// preproc_axis.v —— IP1 图像预处理
// 功能：RGB -> 灰度(BT.601) -> 2x 降采样（无高斯：实测 3x3 高斯伤小目标 Pd 95%->81%，故去掉）
// 输入：W_IN x H_IN 的 RGB 像素流（行优先，i_valid 每周期一个像素）
// 输出：(W_IN/2) x (H_IN/2) 的灰度图（降采样后）
// 定点约定：gray = (4899R+9617G+1868B+8192)>>14（OpenCV BGR2GRAY 精确 14bit 定点，0 误差）
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

    // ---- 输出阶段：直接输出降采样灰度（无高斯）----
    wire [3:0] o_row = out_cnt[7:4];   // 0..15
    wire [3:0] o_col = out_cnt[3:0];   // 0..15

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
                            gray_mem[ds_row][ds_col] <= (i_r*4899 + i_g*9617 + i_b*1868 + 8192) >> 14;
                        in_cnt <= in_cnt + 10'd1;
                        if (in_cnt == IN_TOTAL - 1) begin
                            state   <= S_OUT;
                            out_cnt <= 8'd0;
                        end
                    end
                end
                S_OUT: begin
                    o_data  <= gray_mem[o_row][o_col];
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
