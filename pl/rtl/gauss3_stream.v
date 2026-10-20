// gauss3_stream.v —— 流式 3x3 高斯（行缓存 + 流水线 + AXI4-Stream）
// 2 行行缓存（每行 W+1 深，tap 在 W-1 读旧值 = 上一行同列）
module gauss3_stream #(
    parameter W = 16,
    parameter H = 16
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] s_axis_tdata,
    input  wire s_axis_tvalid,
    output wire s_axis_tready,
    input  wire s_axis_tlast,
    output wire [7:0] m_axis_tdata,
    output wire m_axis_tvalid,
    input  wire m_axis_tready,
    output wire m_axis_tlast
);
    localparam DELAY = W + 2;

    reg [7:0] lb0 [0:W];
    reg [7:0] lb1 [0:W];
    reg [7:0] cur  [0:2];
    reg [7:0] prev [0:2];
    reg [7:0] prev2[0:2];

    wire hs = s_axis_tvalid && s_axis_tready;
    assign s_axis_tready = m_axis_tready;

    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i <= W; i = i + 1) begin lb0[i] <= 8'd0; lb1[i] <= 8'd0; end
            for (i = 0; i < 3; i = i + 1) begin cur[i] <= 8'd0; prev[i] <= 8'd0; prev2[i] <= 8'd0; end
        end else if (hs) begin
            lb1[0] <= lb0[W-1];
            for (i = 1; i <= W; i = i + 1) lb1[i] <= lb1[i-1];
            lb0[0] <= s_axis_tdata;
            for (i = 1; i <= W; i = i + 1) lb0[i] <= lb0[i-1];
            prev2[0] <= lb1[W-1]; prev2[1] <= prev2[0]; prev2[2] <= prev2[1];
            prev[0]  <= lb0[W-1]; prev[1]  <= prev[0];  prev[2]  <= prev[1];
            cur[0]   <= s_axis_tdata; cur[1] <= cur[0]; cur[2] <= cur[1];
        end
    end

    wire [11:0] gsum =
        prev2[2] + (prev2[1] << 1) + prev2[0] +
        (prev[2] << 1) + (prev[1] << 2) + (prev[0] << 1) +
        cur[2] + (cur[1] << 1) + cur[0];
    wire [7:0] gauss = (gsum + 12'd8) >> 4;

    reg [DELAY-1:0] valid_shift;
    reg [DELAY-1:0] last_shift;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_shift <= {DELAY{1'b0}};
            last_shift  <= {DELAY{1'b0}};
        end else if (m_axis_tready) begin
            valid_shift <= {valid_shift[DELAY-2:0], s_axis_tvalid};
            last_shift  <= {last_shift[DELAY-2:0],  s_axis_tlast};
        end
    end

    assign m_axis_tdata  = gauss;
    assign m_axis_tvalid = valid_shift[DELAY-1];
    assign m_axis_tlast  = last_shift[DELAY-1];
endmodule
