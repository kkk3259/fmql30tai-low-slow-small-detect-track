// tb_ccl_centroid.v —— 验证质心除法位宽（大目标 x 不再溢出）
// 目标：640x360，背景 40，一块 16x16 亮块 (320..335, 180..195) 值 240
// 期望：n=1，x≈327，y≈187，area=256
`timescale 1ns/1ps
module tb_ccl_centroid;
    localparam W = 640, H = 360;
    reg clk = 0, rst_n = 0;
    reg [7:0] px = 8'd0;
    wire bin_px = (px >= 8'd128);
    always #10 clk = ~clk;

    reg [7:0] id = 0;
    reg iv = 0;
    wire irdy, ov, ordy;
    wire [7:0] od;
    assign ordy = 1'b1;

    candidate_extract_stream #(.W(W), .H(H), .MAX_CAND(64)) dut (
        .clk(clk), .rst_n(rst_n),
        .i_bin_valid(iv), .i_bin(bin_px), .i_enh_valid(iv), .i_enh(id),
        .o_data(od), .o_valid(ov), .o_ready(ordy),
        .dbg_state(), .dbg_px(), .dbg_vcnt()
    );

    integer x, y, i;
    reg [7:0] bytes [0:451];
    integer nbytes = 0;

    initial begin
        rst_n = 0;
        repeat (8) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        for (y = 0; y < H; y = y + 1) begin
            for (x = 0; x < W; x = x + 1) begin
                px = ((x >= 320) && (x < 336) && (y >= 180) && (y < 196)) ? 8'd240 : 8'd40;
                @(negedge clk);
                id = px; iv = 1'b1;
                @(posedge clk);
                while (!irdy) @(posedge clk);
            end
        end
        @(negedge clk); iv = 1'b0;
        repeat (40000) @(posedge clk);

        $display("采集到 %0d 字节", nbytes);
        if (nbytes > 0) begin
            $display("n_cand = %0d", bytes[0]);
            for (i = 0; i < bytes[0] && i < 3; i = i + 1) begin
                $display("  cand%0d: x=%0d y=%0d area=%0d peak=%0d", i,
                    {bytes[1+7*i], bytes[2+7*i]}, {bytes[3+7*i], bytes[4+7*i]},
                    {bytes[5+7*i], bytes[6+7*i]}, bytes[7+7*i]);
            end
        end
        $finish;
    end

    always @(posedge clk) begin
        if (ov && ordy) begin
            bytes[nbytes] <= od;
            nbytes <= nbytes + 1;
        end
    end
endmodule
