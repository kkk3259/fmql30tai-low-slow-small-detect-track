// tb_denoise2.v —— 探针版：打印帧内前若干拍的内部信号
`timescale 1ns/1ps
module tb_denoise2;
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

    integer i, x, y, k;

    initial begin
        for (i = 0; i < N; i = i + 1) img[i] = 8'd0;
        for (y = 2; y <= 4; y = y + 1)
            for (x = 2; x <= 4; x = x + 1) img[y * W + x] = 8'd9;
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
        for (i = 0; i < 4 * W; i = i + 1) begin
            @(negedge clk);
            i_bin = 1'b0; i_enh = 8'd0;
            i_bin_valid = 1'b1; i_enh_valid = 1'b1;
        end
        @(negedge clk); i_bin_valid = 1'b0; i_enh_valid = 1'b0;
        repeat (2000) @(posedge clk);
        $display("state=%0d px=%0d vcnt=%0d ncomp=%0d", dbg_state, dbg_px, dbg_vcnt, dut.n_comp);
        $finish;
    end

    // 每拍打印（前 120 拍）
    initial begin
        for (k = 0; k < 120; k = k + 1) begin
            @(posedge clk);
            #1;
            $display("k=%0d in=%b vin=%0d st=%0d nb_c=%0d nb_p=%b cnt=%0d fbin=%b fvld=%b ctr=%b rm1=%b n2=%b n1c=%b",
                     k, i_bin, dut.vin, dut.state, dut.nb_c, dut.nb_p, dut.nb_cnt,
                     dut.f_bin, dut.f_valid_r, dut.n1_m1, dut.n1_m2, dut.n2_m1, dut.n1_c);
        end
    end
endmodule
