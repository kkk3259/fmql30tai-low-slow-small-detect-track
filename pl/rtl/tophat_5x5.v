// tophat_5x5.v —— IP2 子模块①：5x5 Top-Hat 形态学
// TopHat = I - opening(I) = I - dilate(erode(I, 5x5), 5x5)
// 输入：W x H 灰度图（行优先流）
// 输出：同尺寸 Top-Hat 结果（饱和减法，clip 到 [0,255]）
module tophat_5x5 #(
    parameter W = 32,
    parameter H = 32
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] i_data,
    input  wire i_valid,
    output reg  [7:0] o_data,
    output reg  o_valid,
    input  wire o_ready
);
    localparam N = W * H;

    reg [7:0] gray    [0:H-1][0:W-1];
    reg [7:0] eroded  [0:H-1][0:W-1];
    reg [7:0] dilated [0:H-1][0:W-1];

    reg [9:0] cnt;
    reg [2:0] state;
    localparam S_IN = 3'd0, S_ERODE = 3'd1, S_DILATE = 3'd2, S_OUT = 3'd3, S_DONE = 3'd4;

    wire [4:0] r = cnt[9:5];
    wire [4:0] c = cnt[4:0];

    // 5x5 窗口行列（边界 clamp，内部像素精确）
    wire [4:0] r0 = (r >= 5'd2) ? r - 5'd2 : 5'd0;
    wire [4:0] r1 = (r >= 5'd1) ? r - 5'd1 : 5'd0;
    wire [4:0] r2 = r;
    wire [4:0] r3 = (r <= H-2) ? r + 5'd1 : H-1;
    wire [4:0] r4 = (r <= H-3) ? r + 5'd2 : H-1;
    wire [4:0] c0 = (c >= 5'd2) ? c - 5'd2 : 5'd0;
    wire [4:0] c1 = (c >= 5'd1) ? c - 5'd1 : 5'd0;
    wire [4:0] c2 = c;
    wire [4:0] c3 = (c <= W-2) ? c + 5'd1 : W-1;
    wire [4:0] c4 = (c <= W-3) ? c + 5'd2 : W-1;

    // 5 取最小 / 最大
    function [7:0] min5;
        input [7:0] a, b, c, d, e;
        reg [7:0] m;
        begin
            m = (a < b) ? a : b;
            m = (m < c) ? m : c;
            m = (m < d) ? m : d;
            min5 = (m < e) ? m : e;
        end
    endfunction
    function [7:0] max5;
        input [7:0] a, b, c, d, e;
        reg [7:0] m;
        begin
            m = (a > b) ? a : b;
            m = (m > c) ? m : c;
            m = (m > d) ? m : d;
            max5 = (m > e) ? m : e;
        end
    endfunction

    // 腐蚀（5x5 最小）= 对 gray 求窗口最小值
    wire [7:0] erode_val =
        min5(min5(gray[r0][c0], gray[r0][c1], gray[r0][c2], gray[r0][c3], gray[r0][c4]),
             min5(gray[r1][c0], gray[r1][c1], gray[r1][c2], gray[r1][c3], gray[r1][c4]),
             min5(gray[r2][c0], gray[r2][c1], gray[r2][c2], gray[r2][c3], gray[r2][c4]),
             min5(gray[r3][c0], gray[r3][c1], gray[r3][c2], gray[r3][c3], gray[r3][c4]),
             min5(gray[r4][c0], gray[r4][c1], gray[r4][c2], gray[r4][c3], gray[r4][c4]));

    // 膨胀（5x5 最大）= 对 eroded 求窗口最大值
    wire [7:0] dilate_val =
        max5(max5(eroded[r0][c0], eroded[r0][c1], eroded[r0][c2], eroded[r0][c3], eroded[r0][c4]),
             max5(eroded[r1][c0], eroded[r1][c1], eroded[r1][c2], eroded[r1][c3], eroded[r1][c4]),
             max5(eroded[r2][c0], eroded[r2][c1], eroded[r2][c2], eroded[r2][c3], eroded[r2][c4]),
             max5(eroded[r3][c0], eroded[r3][c1], eroded[r3][c2], eroded[r3][c3], eroded[r3][c4]),
             max5(eroded[r4][c0], eroded[r4][c1], eroded[r4][c2], eroded[r4][c3], eroded[r4][c4]));

    // Top-Hat = 原图 - 开运算（饱和减）
    wire [7:0] tophat_val = (gray[r2][c2] >= dilate_val) ? (gray[r2][c2] - dilate_val) : 8'd0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 10'd0;
            state <= S_IN;
            o_data <= 8'd0;
            o_valid <= 1'b0;
        end else begin
            case (state)
                S_IN: begin
                    if (i_valid) begin
                        gray[r][c] <= i_data;
                        if (cnt == N-1) begin state <= S_ERODE; cnt <= 10'd0; end
                        else cnt <= cnt + 10'd1;
                    end
                end
                S_ERODE: begin
                    eroded[r][c] <= erode_val;
                    if (cnt == N-1) begin state <= S_DILATE; cnt <= 10'd0; end
                    else cnt <= cnt + 10'd1;
                end
                S_DILATE: begin
                    dilated[r][c] <= dilate_val;
                    if (cnt == N-1) begin state <= S_OUT; cnt <= 10'd0; end
                    else cnt <= cnt + 10'd1;
                end
                S_OUT: begin
                    o_data <= tophat_val;
                    o_valid <= 1'b1;
                    if (o_ready) begin
                        if (cnt == N-1) state <= S_DONE;
                        else cnt <= cnt + 10'd1;
                    end
                end
                S_DONE: begin
                    o_valid <= 1'b0;
                end
            endcase
        end
    end
endmodule
