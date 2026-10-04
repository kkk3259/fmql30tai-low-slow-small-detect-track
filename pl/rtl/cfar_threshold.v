// cfar_threshold.v —— IP2 子模块②：CFAR 自适应阈值（定点 MAD 版，可综合）
// thr = 局部均值 + k×局部MAD + floor（31x31 窗口）；img > thr 判为目标(255)，否则 0
// 定点化：把原来的 real + $sqrt(标准差) 换成整数 MAD(平均绝对偏差)，避开开方。
//   MAD ≈ 0.8×std（高斯噪声），故 k 由 4.0 调整为 5（约 4.0/0.8），floor 保持 3。
// 说明：这是"资源-精度取舍"——MAD 比 std 略粗略，但无需 sqrt，可综合且省资源。
module cfar_threshold #(
    parameter W = 64,
    parameter H = 64,
    parameter WIN = 31,      // 窗口尺寸
    parameter K = 5,         // MAD 系数（近似 std 的 k=4.0）
    parameter FLOOR = 3      // 阈值下限
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
    localparam WIN_AREA = WIN * WIN;   // 961
    localparam HALF = WIN / 2;         // 15

    reg [7:0] img [0:H-1][0:W-1];
    reg [7:0] bin [0:H-1][0:W-1];

    reg [CNT_W-1:0] cnt;
    reg [1:0]  state;
    localparam S_IN = 2'd0, S_CFAR = 2'd1, S_OUT = 2'd2, S_DONE = 2'd3;

    wire [CH-1:0] r = cnt[CNT_W-1:CW];
    wire [CW-1:0] c = cnt[CW-1:0];

    // 31x31 窗口均值 + MAD（边界 clamp）
    reg [19:0] win_sum;
    reg [19:0] win_abs;
    reg [7:0]  mu, mad;
    reg [15:0] thr_i;
    integer a, b, rr, cc;
    always @* begin
        win_sum = 20'd0;
        for (a = 0; a < WIN; a = a + 1) begin
            rr = r - HALF + a;
            if (rr < 0) rr = 0;
            if (rr > H - 1) rr = H - 1;
            for (b = 0; b < WIN; b = b + 1) begin
                cc = c - HALF + b;
                if (cc < 0) cc = 0;
                if (cc > W - 1) cc = W - 1;
                win_sum = win_sum + img[rr][cc];
            end
        end
        mu = win_sum / WIN_AREA;
        win_abs = 20'd0;
        for (a = 0; a < WIN; a = a + 1) begin
            rr = r - HALF + a;
            if (rr < 0) rr = 0;
            if (rr > H - 1) rr = H - 1;
            for (b = 0; b < WIN; b = b + 1) begin
                cc = c - HALF + b;
                if (cc < 0) cc = 0;
                if (cc > W - 1) cc = W - 1;
                win_abs = win_abs + ((img[rr][cc] >= mu) ? (img[rr][cc] - mu) : (mu - img[rr][cc]));
            end
        end
        mad   = win_abs / WIN_AREA;
        thr_i = mu + K * mad + FLOOR;
    end

    wire [7:0] binary = (img[r][c] > thr_i) ? 8'd255 : 8'd0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 0; state <= S_IN; o_data <= 8'd0; o_valid <= 1'b0;
        end else begin
            case (state)
                S_IN: begin
                    if (i_valid) begin
                        img[r][c] <= i_data;
                        if (cnt == N - 1) begin state <= S_CFAR; cnt <= 0; end
                        else cnt <= cnt + 1;
                    end
                end
                S_CFAR: begin
                    bin[r][c] <= binary;
                    if (cnt == N - 1) begin state <= S_OUT; cnt <= 0; end
                    else cnt <= cnt + 1;
                end
                S_OUT: begin
                    o_data  <= bin[r][c];
                    o_valid <= 1'b1;
                    if (o_ready) begin
                        if (cnt == N - 1) state <= S_DONE;
                        else cnt <= cnt + 1;
                    end
                end
                S_DONE: o_valid <= 1'b0;
            endcase
        end
    end
endmodule
