// roi_pack.v —— IP4：裁 128x128 ROI（I3 接口，PL → NPU）
// 输入：降采样灰度图（W×H）+ 候选列表（I2，36 字节）
// 输出：对每个候选，裁以 (cx,cy) 为中心、128x128 的图块（越界补 0），逐字节流式输出
// 语义对齐 ps_app.py::crop_roi（x0=cx-64, y0=cy-64，越界补 0）
module roi_pack #(
    parameter W = 160,
    parameter H = 160,
    parameter ROI = 128,
    parameter MAX_CAND = 5
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] i_data,     // S_GRAY 时是灰度像素，S_CAND 时是候选字节
    input  wire i_valid,
    output reg  [7:0] o_data,
    output reg  o_valid,
    input  wire o_ready
);
    localparam N       = W * H;
    localparam CW      = $clog2(W);
    localparam CH      = $clog2(H);
    localparam CNT_W   = $clog2(N);
    localparam HALF    = ROI / 2;              // 64
    localparam ROI_W   = $clog2(ROI);          // 7
    localparam ROI_AREA = ROI * ROI;           // 16384
    localparam ROI_CNT = 2 * ROI_W;            // 14

    reg [7:0] gray [0:H-1][0:W-1];
    reg [7:0] cbytes [0:35];       // 36 字节候选列表 = n_cand + 5×7
    reg [15:0] cx [0:MAX_CAND-1];
    reg [15:0] cy [0:MAX_CAND-1];
    reg [7:0] n_cand;

    reg [CNT_W-1:0] cnt;
    reg [ROI_CNT-1:0] roi_cnt;
    reg [3:0] cand_i;
    reg [2:0] state;
    localparam S_GRAY = 0, S_CAND = 1, S_CROP = 2, S_DONE = 3;

    wire [CH-1:0] gr = cnt / W;
    wire [CW-1:0] gc = cnt % W;

    integer i;
    always @* begin
        n_cand = cbytes[0];
        for (i = 0; i < MAX_CAND; i = i + 1) begin
            cx[i] = (cbytes[1 + i*7] << 8) | cbytes[2 + i*7];
            cy[i] = (cbytes[3 + i*7] << 8) | cbytes[4 + i*7];
        end
    end

    // ROI 像素坐标
    wire [ROI_W-1:0] roi_c = roi_cnt[ROI_W-1:0];       // 列 0..127
    wire [ROI_W-1:0] roi_r = roi_cnt[ROI_CNT-1:ROI_W]; // 行 0..127

    // gx = cx - 64 + roi_c，gy = cy - 64 + roi_r（有符号）
    integer gx_i, gy_i;
    always @* begin
        gx_i = cx[cand_i] - HALF + roi_c;
        gy_i = cy[cand_i] - HALF + roi_r;
    end
    wire in_bounds = (gx_i >= 0) && (gx_i < W) && (gy_i >= 0) && (gy_i < H);
    wire [7:0] roi_val = in_bounds ? gray[gy_i][gx_i] : 8'd0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 0; roi_cnt <= 0; cand_i <= 0; state <= S_GRAY;
            o_data <= 8'd0; o_valid <= 1'b0;
        end else begin
            case (state)
                S_GRAY: begin
                    if (i_valid) begin
                        gray[gr][gc] <= i_data;
                        if (cnt == N - 1) begin state <= S_CAND; cnt <= 0; end
                        else cnt <= cnt + 1;
                    end
                end
                S_CAND: begin
                    if (i_valid) begin
                        cbytes[cnt] <= i_data;
                        if (cnt == 35) begin state <= S_CROP; roi_cnt <= 0; cand_i <= 0; end
                        else cnt <= cnt + 1;
                    end
                end
                S_CROP: begin
                    o_data  <= roi_val;
                    o_valid <= 1'b1;
                    if (o_ready) begin
                        if (roi_cnt == ROI_AREA - 1) begin
                            roi_cnt <= 0;
                            if (cand_i == n_cand - 1) state <= S_DONE;
                            else cand_i <= cand_i + 1;
                        end else roi_cnt <= roi_cnt + 1;
                    end
                end
                S_DONE: o_valid <= 1'b0;
            endcase
        end
    end
endmodule
