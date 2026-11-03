//======================================================================
// tb_line_gen.v —— 验证行流拆包（v2：平台模型用 fork/join_none，无状态机）
//
// 平台模型：一次只接一个 AR，3 拍后返回该行 64 字节；内容 byte[i]=(i*7+11)&0xFF
// 判据：  收到的字节数 == NPIX，且逐字节一致
//======================================================================
`timescale 1ns / 1ps
module tb_line_gen;
    localparam W = 64, H = 48;
    localparam NPIX  = W * H;
    localparam NLINE = NPIX / 64;

    reg clk = 0, rst_n = 0;
    always #2.5 clk = ~clk;

    reg         start = 0;
    reg  [31:0] base  = 32'h0000_1000;

    wire [31:0]  araddr;
    wire         arvalid;
    reg  inflight = 0;                  // 一次只接一个 AR
    reg  [31:0] pa = 0;
    wire         arready = !inflight;
    reg  [511:0] rdata = 0;
    reg          rvalid = 0;
    wire [7:0]   o_data;
    wire         o_valid;
    reg          o_ready = 0;
    wire [15:0]  lines_done;
    wire         busy;

    ip2_line_gen #(.NPIX(NPIX)) dut (
        .clk(clk), .rst_n(rst_n), .start(start), .base_addr(base),
        .itf_araddr(araddr), .itf_arvalid(arvalid), .itf_arready(arready),
        .itf_rdata(rdata), .itf_rvalid(rvalid),
        .o_data(o_data), .o_valid(o_valid), .o_ready(o_ready),
        .o_lines_done(lines_done), .o_busy(busy)
    );

    function [7:0] mbyte(input integer i);
        mbyte = (i * 7 + 11) & 8'hFF;
    endfunction



    // ---- 平台：收到 AR 就 fork 一个线程，3 拍后返回该行 ----
    integer n_ar = 0;
    integer k;
    always @(posedge clk) begin
        if (rst_n && arvalid && arready && !inflight) begin
            pa <= araddr;
            inflight <= 1;
            if (n_ar < 4) $display("AR#%0d addr=%0d offset=%0d", n_ar, araddr, araddr-32'h0000_1000);
            n_ar = n_ar + 1;
            fork
                begin
                    repeat (3) @(posedge clk);
                    for (k = 0; k < 64; k = k + 1)
                        rdata[k*8 +: 8] <= mbyte(pa - 32'h0000_1000 + k);
                    rvalid <= 1;
                    @(posedge clk);
                    rvalid <= 0;
                    @(posedge clk);
                    inflight <= 0;
                end
            join_none
        end
    end

    // ---- 收集 ----
    integer got_n = 0, err_n = 0;
    reg [7:0] got [0:NPIX+512];

    always @(negedge clk) begin
        if (rst_n && o_valid && o_ready) begin
            got[got_n] = o_data;
            if (o_data !== mbyte(got_n)) begin
                if (err_n < 6) $display("  MISMATCH idx=%0d got=%0d exp=%0d", got_n, o_data, mbyte(got_n));
                err_n = err_n + 1;
            end
            got_n = got_n + 1;
        end
    end

    initial begin
        repeat (5) @(posedge clk);
        rst_n = 1;
        repeat (2) @(posedge clk);
        start <= 1;
        @(posedge clk);
        start <= 0;
        o_ready <= 1;

        fork : w
            begin wait (got_n >= NPIX); disable w; end
            begin repeat (NPIX * 6) @(posedge clk); disable w; end
        join
        repeat (20) @(posedge clk);

        $display("");
        $display("收到字节 = %0d  (期望 %0d)", got_n, NPIX);
        $display("行数     = %0d  (期望 %0d)", lines_done, NLINE);
        $display("不一致   = %0d", err_n);
        $display("前 8 实测: %0d %0d %0d %0d %0d %0d %0d %0d", got[0],got[1],got[2],got[3],got[4],got[5],got[6],got[7]);
        $display("前 8 期望: %0d %0d %0d %0d %0d %0d %0d %0d", mbyte(0),mbyte(1),mbyte(2),mbyte(3),mbyte(4),mbyte(5),mbyte(6),mbyte(7));
        $display("64~71 实测: %0d %0d %0d %0d", got[64],got[65],got[66],got[67]);
        if (got_n >= NPIX && err_n == 0) $display("VERDICT LINE-GEN-OK");
        else                              $display("VERDICT LINE-GEN-FAIL");
        $finish;
    end

    initial begin
        #20_000_000;
        $display("TIMEOUT got=%0d err=%0d lines=%0d", got_n, err_n, lines_done);
        $display("VERDICT LINE-GEN-TIMEOUT");
        $finish;
    end
endmodule
