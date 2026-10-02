// candidate_extract.v —— IP2 子模块③：候选提取（v1 简化版：8x8 分块统计）
// 把二值图分成 8x8 块，统计每块内的亮点个数（area）。area>0 的块即"粗筛候选"。
// 精确版（连通域标记 CCL + 质心/面积/峰值）是后续加分项。
module candidate_extract #(
    parameter W = 64,
    parameter H = 64
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] i_data,
    input  wire i_valid,
    output reg  [7:0] o_data,
    output reg  o_valid,
    input  wire o_ready
);
    localparam N   = W * H;       // 4096
    localparam NB  = 64;          // 8x8 = 64 块
    localparam BW  = 8;           // 块宽

    reg [7:0] bin [0:H-1][0:W-1];
    reg [7:0] area [0:NB-1];

    reg [15:0] cnt;
    reg [1:0]  state;
    localparam S_IN = 2'd0, S_BLK = 2'd1, S_OUT = 2'd2, S_DONE = 2'd3;

    wire [5:0] r = cnt[11:6];
    wire [5:0] c = cnt[5:0];

    // 块处理：blk = 0..63，每块的面积 = 64 像素里亮点个数
    wire [5:0] blk = cnt[5:0];            // 0..63
    wire [2:0] blk_row = blk[5:3];
    wire [2:0] blk_col = blk[2:0];
    reg  [6:0] blk_area;
    integer p, py, px, ay, ax;
    always @* begin
        blk_area = 7'd0;
        for (p = 0; p < 64; p = p + 1) begin
            py = p / 8;
            px = p - py * 8;
            ay = blk_row * 8 + py;
            ax = blk_col * 8 + px;
            if (bin[ay][ax] > 0)
                blk_area = blk_area + 7'd1;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 16'd0; state <= S_IN; o_data <= 8'd0; o_valid <= 1'b0;
        end else begin
            case (state)
                S_IN: begin
                    if (i_valid) begin
                        bin[r][c] <= i_data;
                        if (cnt == N - 1) begin state <= S_BLK; cnt <= 16'd0; end
                        else cnt <= cnt + 16'd1;
                    end
                end
                S_BLK: begin
                    area[blk] <= blk_area;
                    if (blk == NB - 1) begin state <= S_OUT; cnt <= 16'd0; end
                    else cnt <= cnt + 16'd1;
                end
                S_OUT: begin
                    o_data  <= area[cnt[5:0]];
                    o_valid <= 1'b1;
                    if (o_ready) begin
                        if (cnt[5:0] == NB - 1) state <= S_DONE;
                        else cnt <= cnt + 16'd1;
                    end
                end
                S_DONE: o_valid <= 1'b0;
            endcase
        end
    end
endmodule
