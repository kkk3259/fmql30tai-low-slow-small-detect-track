// ============================================================================
// tb_board_pattern.v —— 上板逻辑（除时钟缓冲外的全部）的仿真验证
//
// 目的：在跑昂贵的 Procise 综合之前，确认 ip2_pattern_gen + ip2_frame_top
//       的帧循环（F_FEED -> F_WAIT -> F_RST）能正常出结果，且：
//         · 4 个 3x3 亮点被检出为候选
//         · 1 个大亮块（面积 > MAX_AREA）被面积门限滤掉
// 分辨率用 128x72 以缩短仿真时间（链路参数化，逻辑与 640x360 完全相同）。
// 注：ip2_board_top.v 里有 IBUFDS/BUFG 原语，仿真时不编译它，直接例化
//     ip2_frame_top（board_top 里除时钟分频外没有其他逻辑）。
// ============================================================================
`timescale 1ns/1ps

module tb_board_pattern;

    localparam W = 128;
    localparam H = 72;
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

    // ---- 抓图案前若干像素，确认图案确实生成了 ----
    integer   psamp = 0;
    always @(posedge clk) begin
        if (u_frame.pg_valid && u_frame.ch_ready && (psamp < 6)) begin
            $display("PIX %0d = %0d", psamp, u_frame.pg_data);
            psamp = psamp + 1;
        end
    end

    integer k;
    integer guard;

    initial begin
        rst_n = 1'b0;
        repeat (40) @(posedge clk);
        rst_n = 1'b1;

        // 等 3 帧闭环（fcnt 变 3），验证帧循环可以反复跑
        guard = 0;
        while ((u_frame.fcnt < 12'd3) && (guard < 5000000)) begin
            @(posedge clk);
            guard = guard + 1;
        end
        repeat (10) @(posedge clk);

        $display("RESULT frames=%0d ncand=%0d ocount=%0d bytes_captured=%0d led=%b",
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

        if (u_frame.fcnt < 12'd3) begin
            $display("VERDICT TIMEOUT");
        end else if (u_frame.ncand != 8'd4) begin
            $display("VERDICT CAND-MISMATCH (expect 4, got %0d)", u_frame.ncand);
        end else begin
            $display("VERDICT FRAME-OK (3 frames, 4 candidates each)");
        end

        $finish;
    end

endmodule
