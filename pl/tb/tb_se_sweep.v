// tb_se_sweep.v —— 单目标尺寸扫描（160x120，不带 AXI，快）
// 用法：vvp se_sweep.vvp +ts=12
// 目的：用仿真回答“SE=21 的 Top-Hat 到底能认出多大的目标”，不依赖板子。
`timescale 1ns/1ps
module tb_se_sweep;
    localparam W = 160;
    localparam H = 120;
    localparam NPIX = W*H;                        // 19200
    localparam PADN = (W+15)*(H+15) - NPIX + 512; // 把 CFAR 流水线排空

    reg clk, rst_n;
    reg [7:0] i_data;
    reg i_valid;
    wire i_ready;
    wire [7:0] o_data;
    wire o_valid;
    reg o_ready;

    reg [7:0] in_mem [0:NPIX-1];
    reg [7:0] out_mem [0:35];

    integer idx, out_idx, idle, x, y, TS, cx0, cy0;

    ip2_top_stream #(.W(W), .H(H), .MAX_CAND(5), .SE(21), .MODE(0)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid), .i_ready(i_ready),
        .o_data(o_data), .o_valid(o_valid), .o_ready(o_ready)
    );

    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        if (!$value$plusargs("ts=%d", TS)) TS = 12;
        cx0 = W/2 - TS/2;
        cy0 = H/2 - TS/2;
        for (y = 0; y < H; y = y + 1)
            for (x = 0; x < W; x = x + 1)
                in_mem[y*W + x] = ((x >= cx0) && (x < cx0+TS) &&
                                   (y >= cy0) && (y < cy0+TS)) ? 8'd220 : 8'd40;
    end

    initial begin
        rst_n = 0; i_valid = 0; i_data = 0; o_ready = 1;
        repeat (3) @(posedge clk);
        #1 rst_n = 1;
        repeat (2) @(posedge clk);

        idx = 0;
        i_data = in_mem[0];
        i_valid = 1'b1;
        while (idx < NPIX + PADN) begin
            @(negedge clk);
            if (i_ready) begin
                idx = idx + 1;
                i_data = (idx < NPIX) ? in_mem[idx] : 8'd0;
            end
        end
        @(negedge clk);
        i_valid = 1'b0;
    end

    initial begin
        wait (rst_n === 1'b1);
        out_idx = 0; idle = 0;
        while (out_idx < 36) begin
            @(posedge clk);
            if (o_valid) begin
                out_mem[out_idx] = o_data;
                out_idx = out_idx + 1;
                idle = 0;
            end else begin
                idle = idle + 1;
                if (idle > 3000000) begin
                    $display("SWEEP ts=%0d TIMEOUT ocount=%0d", TS, out_idx);
                    $finish;
                end
            end
        end
        begin : P
            integer k, xx, yy, ar, pk;
            $display("SWEEP ts=%0d n_cand=%0d", TS, out_mem[0]);
            for (k = 0; k < out_mem[0] && k < 5; k = k + 1) begin
                xx = (out_mem[1+k*7] << 8) | out_mem[2+k*7];
                yy = (out_mem[3+k*7] << 8) | out_mem[4+k*7];
                ar = (out_mem[5+k*7] << 8) | out_mem[6+k*7];
                pk = out_mem[7+k*7];
                $display("  cand%0d x=%0d y=%0d area=%0d peak=%0d", k, xx, yy, ar, pk);
            end
        end
        #50 $finish;
    end
endmodule
