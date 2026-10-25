// ============================================================================
// tb_board_pattern640.v —— 640x360 上板逻辑（io2_frame_top）的整帧仿真
//
// 目的：板子上 4 个 LED 全亮，怀疑 ncand 饱和（>7）。本 tb 用与上板完全相同
//       的 640x360 图案，跑 2 帧，打印 ncand 与候选表，作为硬件观测的对照。
// 说明：ip2_board_top.v 含 IBUFDS/BUFG 原语，仿真不编译它，直接例化
//       ip2_frame_top（board_top 里除时钟分频外没有其他逻辑）。
// ============================================================================
`timescale 1ns/1ps

module tb_board_pattern640;

    localparam W = 640;
    localparam H = 360;
    localparam NBYTE = 36;

    reg         clk = 1'b0;
    reg         rst_n = 1'b0;
    wire [3:0]  led;

    always #5 clk = ~clk;          // 100MHz

    ip2_frame_top #(
        .W        (W),
        .H        (H),
        .MAX_CAND (5)
    ) u_frame (
        .clk   (clk),
        .rst_n (rst_n),
        .led   (led)
    );

    // ---- 抓 CCL 吐出的 36 字节（每帧重新开始）----
    reg [7:0] bytes [0:NBYTE-1];
    integer   nb = 0;
    integer   fr = 0;
    always @(posedge clk) begin
        if (u_frame.fcnt != fr) begin
            fr = u_frame.fcnt;
            nb = 0;
        end
        if (u_frame.ccl_valid && (nb < NBYTE)) begin
            bytes[nb] = u_frame.ccl_data;
            nb = nb + 1;
        end
    end

    integer k;
    integer guard;

    initial begin
        rst_n = 1'b0;
        repeat (40) @(posedge clk);
        rst_n = 1'b1;

        guard = 0;
        while ((u_frame.fcnt < 12'd2) && (guard < 20000000)) begin
            @(posedge clk);
            guard = guard + 1;
        end
        repeat (10) @(posedge clk);

        $display("RESULT frames=%0d ncand=%0d ocount=%0d bytes=%0d led=%b",
                 u_frame.fcnt, u_frame.ncand, u_frame.ocount, nb, led);

        for (k = 0; k < 5; k = k + 1) begin
            if (bytes[1 + k*7 + 6] !== 8'hxx) begin
                $display("CAND %0d: x=%0d y=%0d area=%0d peak=%0d",
                    k,
                    {bytes[1+k*7], bytes[2+k*7]},
                    {bytes[3+k*7], bytes[4+k*7]},
                    bytes[1+k*7+5],
                    bytes[1+k*7+6]);
            end
        end

        if (u_frame.fcnt < 12'd2) begin
            $display("VERDICT TIMEOUT");
        end else if (u_frame.ncand != 8'd4) begin
            $display("VERDICT CAND-MISMATCH (expect 4, got %0d)", u_frame.ncand);
        end else begin
            $display("VERDICT FRAME-OK (640x360, 4 candidates)");
        end

        $finish;
    end

endmodule
