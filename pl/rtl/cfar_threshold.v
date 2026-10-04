// cfar_threshold.v —— IP2 子模块②：CFAR 自适应阈值
// thr = 局部均值 + 4.0*局部标准差 + 3.0（31x31 窗口）；img > thr 判为目标(255)，否则 0
// 说明：本版用 real 算术对齐 OpenCV 的 float 计算（单元验证用）；
//       上板前再替换为定点 + MAD 近似（避开 sqrt），这是"资源-精度取舍"的加分点。
module cfar_threshold #(
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
    localparam N = W * H;
    localparam CW = $clog2(W);
    localparam CH = $clog2(H);
    localparam CNT_W = CW + CH;

    reg [7:0] img [0:H-1][0:W-1];
    reg [7:0] bin [0:H-1][0:W-1];

    reg [CNT_W-1:0] cnt;
    reg [1:0]  state;
    localparam S_IN = 2'd0, S_CFAR = 2'd1, S_OUT = 2'd2, S_DONE = 2'd3;

    wire [CH-1:0] r = cnt[CNT_W-1:CW];
    wire [CW-1:0] c = cnt[CW-1:0];

    // 31x31 窗口求和 + 平方和（边界 clamp，内部像素精确）
    reg [19:0] win_sum;
    reg [27:0] win_sum2;
    integer a, b, rr, cc;
    always @* begin
        win_sum  = 20'd0;
        win_sum2 = 28'd0;
        for (a = 0; a < 31; a = a + 1) begin
            rr = r - 15 + a;
            if (rr < 0) rr = 0;
            if (rr > H - 1) rr = H - 1;
            for (b = 0; b < 31; b = b + 1) begin
                cc = c - 15 + b;
                if (cc < 0) cc = 0;
                if (cc > W - 1) cc = W - 1;
                win_sum  = win_sum  + img[rr][cc];
                win_sum2 = win_sum2 + img[rr][cc] * img[rr][cc];
            end
        end
    end

    // 阈值（real 对齐 OpenCV float）
    real mu, mu2, variance, sd, thr;
    always @* begin
        mu       = win_sum / 961.0;
        mu2      = win_sum2 / 961.0;
        variance = mu2 - mu * mu;
        if (variance < 0.0) variance = 0.0;
        sd  = $sqrt(variance);
        thr = mu + 4.0 * sd + 3.0;
    end

    wire [7:0] binary = (img[r][c] > thr) ? 8'd255 : 8'd0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 16'd0; state <= S_IN; o_data <= 8'd0; o_valid <= 1'b0;
        end else begin
            case (state)
                S_IN: begin
                    if (i_valid) begin
                        img[r][c] <= i_data;
                        if (cnt == N - 1) begin state <= S_CFAR; cnt <= 16'd0; end
                        else cnt <= cnt + 16'd1;
                    end
                end
                S_CFAR: begin
                    bin[r][c] <= binary;
                    if (cnt == N - 1) begin state <= S_OUT; cnt <= 16'd0; end
                    else cnt <= cnt + 16'd1;
                end
                S_OUT: begin
                    o_data  <= bin[r][c];
                    o_valid <= 1'b1;
                    if (o_ready) begin
                        if (cnt == N - 1) state <= S_DONE;
                        else cnt <= cnt + 16'd1;
                    end
                end
                S_DONE: o_valid <= 1'b0;
            endcase
        end
    end
endmodule
