// tb_denoise.v —— 只验证 candidate_extract_stream 的 3×3 去噪窗口
// 图像 16×16：
//   (8,8) 单个孤立前景点        → 应被滤掉
//   (2..4, 2..4) 3×3 实心块     → 应保留（area=9）
//   (10..11, 10..11) 2×2 块     → 应保留（area=4，每点邻域 3 个）
`timescale 1ns/1ps
module tb_denoise;
    localparam W = 16, H = 16, N = W * H;
    reg clk = 0, rst_n = 0;
    reg i_bin = 0, i_bin_valid = 0, i_enh_valid = 0;
    reg [7:0] i_enh = 0;
    wire o_valid;
    wire [7:0] o_data;
    wire [2:0] dbg_state;
    wire [17:0] dbg_px;
    wire [31:0] dbg_vcnt;

    reg [7:0] img [0:N-1];

    candidate_extract_stream #(.W(W), .H(H), .MAX_CAND(8), .MAX_COMP(64),
                               .MIN_AREA(2), .MAX_AREA(2047),
                               .NBR_MIN(3), .DENOISE(1)) dut (
        .clk(clk), .rst_n(rst_n),
        .i_bin(i_bin), .i_bin_valid(i_bin_valid),
        .i_enh(i_enh), .i_enh_valid(i_enh_valid),
        .o_ready(1'b1),
        .o_data(o_data), .o_valid(o_valid),
        .dbg_state(dbg_state), .dbg_px(dbg_px), .dbg_vcnt(dbg_vcnt)
    );

    always #10 clk = ~clk;

    integer i, x, y, got, guard;
    reg [7:0] ob;

    initial begin
        for (i = 0; i < N; i = i + 1) img[i] = 8'd0;
        for (y = 2; y <= 4; y = y + 1)
            for (x = 2; x <= 4; x = x + 1) img[y * W + x] = 8'd9;
        for (y = 10; y <= 11; y = y + 1)
            for (x = 10; x <= 11; x = x + 1) img[y * W + x] = 8'd9;
        img[8 * W + 8] = 8'd9;

        repeat (4) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        for (i = 0; i < N; i = i + 1) begin
            @(negedge clk);
            i_bin = (img[i] > 0);
            i_enh = img[i];
            i_bin_valid = 1'b1;
            i_enh_valid = 1'b1;
        end
        // 帧尾续喂（窗口有 W+2 拍延迟）
        for (i = 0; i < 4 * W; i = i + 1) begin
            @(negedge clk);
            i_bin = 1'b0;
            i_enh = 8'd0;
            i_bin_valid = 1'b1;
            i_enh_valid = 1'b1;
        end
        @(negedge clk);
        i_bin_valid = 1'b0;
        i_enh_valid = 1'b0;

        got = 0; guard = 0;
        while (got < 40 && guard < 20000) begin
            @(posedge clk);
            guard = guard + 1;
            if (o_valid) begin
                ob = o_data;
                $display("byte[%0d] = %02X", got, ob);
                got = got + 1;
            end
        end
        $display("px_cnt=%0d vcnt=%0d state=%0d", dbg_px, dbg_vcnt, dbg_state);
        $display("VERDICT DONE bytes=%0d", got);
        $finish;
    end
endmodule
