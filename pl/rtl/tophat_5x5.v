// tophat_5x5.v —— IP2 子模块①：5x5 Top-Hat 形态学（通用尺寸版）
// TopHat = I - opening(I) = I - dilate(erode(I, 5x5), 5x5)
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
    localparam N     = W * H;
    localparam CW    = $clog2(W);
    localparam RW    = $clog2(H);
    localparam CNT_W = CW + RW;

    reg [7:0] gray    [0:H-1][0:W-1];
    reg [7:0] eroded  [0:H-1][0:W-1];
    reg [7:0] dilated [0:H-1][0:W-1];

    reg [CNT_W-1:0] cnt;
    reg [2:0] state;
    localparam S_IN = 3'd0, S_ERODE = 3'd1, S_DILATE = 3'd2, S_OUT = 3'd3, S_DONE = 3'd4;

    wire [RW-1:0] r = cnt / W;      // 行（真除法，支持非 2 幂宽）
    wire [CW-1:0] c = cnt % W;      // 列（取余）

    // 5x5 窗口行列（边界 clamp，内部像素精确）
    wire [RW-1:0] r0 = (r >= 2) ? r - 2 : {RW{1'b0}};
    wire [RW-1:0] r1 = (r >= 1) ? r - 1 : {RW{1'b0}};
    wire [RW-1:0] r2 = r;
    wire [RW-1:0] r3 = (r <= H-2) ? r + 1 : H-1;
    wire [RW-1:0] r4 = (r <= H-3) ? r + 2 : H-1;
    wire [CW-1:0] c0 = (c >= 2) ? c - 2 : {CW{1'b0}};
    wire [CW-1:0] c1 = (c >= 1) ? c - 1 : {CW{1'b0}};
    wire [CW-1:0] c2 = c;
    wire [CW-1:0] c3 = (c <= W-2) ? c + 1 : W-1;
    wire [CW-1:0] c4 = (c <= W-3) ? c + 2 : W-1;

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

    wire [7:0] erode_val =
        min5(min5(gray[r0][c0], gray[r0][c1], gray[r0][c2], gray[r0][c3], gray[r0][c4]),
             min5(gray[r1][c0], gray[r1][c1], gray[r1][c2], gray[r1][c3], gray[r1][c4]),
             min5(gray[r2][c0], gray[r2][c1], gray[r2][c2], gray[r2][c3], gray[r2][c4]),
             min5(gray[r3][c0], gray[r3][c1], gray[r3][c2], gray[r3][c3], gray[r3][c4]),
             min5(gray[r4][c0], gray[r4][c1], gray[r4][c2], gray[r4][c3], gray[r4][c4]));

    wire [7:0] dilate_val =
        max5(max5(eroded[r0][c0], eroded[r0][c1], eroded[r0][c2], eroded[r0][c3], eroded[r0][c4]),
             max5(eroded[r1][c0], eroded[r1][c1], eroded[r1][c2], eroded[r1][c3], eroded[r1][c4]),
             max5(eroded[r2][c0], eroded[r2][c1], eroded[r2][c2], eroded[r2][c3], eroded[r2][c4]),
             max5(eroded[r3][c0], eroded[r3][c1], eroded[r3][c2], eroded[r3][c3], eroded[r3][c4]),
             max5(eroded[r4][c0], eroded[r4][c1], eroded[r4][c2], eroded[r4][c3], eroded[r4][c4]));

    wire [7:0] tophat_val = (gray[r2][c2] >= dilate_val) ? (gray[r2][c2] - dilate_val) : 8'd0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= {CNT_W{1'b0}};
            state <= S_IN;
            o_data <= 8'd0;
            o_valid <= 1'b0;
        end else begin
            case (state)
                S_IN: begin
                    if (i_valid) begin
                        gray[r][c] <= i_data;
                        if (cnt == N - 1) begin state <= S_ERODE; cnt <= {CNT_W{1'b0}}; end
                        else cnt <= cnt + 1'b1;
                    end
                end
                S_ERODE: begin
                    eroded[r][c] <= erode_val;
                    if (cnt == N - 1) begin state <= S_DILATE; cnt <= {CNT_W{1'b0}}; end
                    else cnt <= cnt + 1'b1;
                end
                S_DILATE: begin
                    dilated[r][c] <= dilate_val;
                    if (cnt == N - 1) begin state <= S_OUT; cnt <= {CNT_W{1'b0}}; end
                    else cnt <= cnt + 1'b1;
                end
                S_OUT: begin
                    o_data  <= tophat_val;
                    o_valid <= 1'b1;
                    if (o_ready) begin
                        if (cnt == N - 1) state <= S_DONE;
                        else cnt <= cnt + 1'b1;
                    end
                end
                S_DONE: o_valid <= 1'b0;
            endcase
        end
    end
endmodule
