// ============================================================================
// tb_board_frames640.v —— 连续多帧仿真，检查"跨帧状态泄漏"
//
// 背景：板上实测 ncand = 3（led[3:1]=011 → D21 灭、D19 亮、D20 亮），
//       而 2 帧的仿真结果是 ncand = 4。差 1 个候选。
// 目的：跑 6 帧，打印每一帧的 ncand，看是否从第 1 帧的 4 漂移到 3。
//       若逐帧变化，说明帧间复位不彻底（cs1/cs2、环形线、parent、标签数组等
//       没有完全清空），这就是板上与仿真的差异来源。
// ============================================================================
`timescale 1ns/1ps

module tb_board_frames640;

    localparam W = 640;
    localparam H = 360;
    localparam NBYTE = 36;
    localparam NFRAME = 6;

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

    reg [7:0] bytes [0:NBYTE-1];
    integer   nb = 0;
    integer   fr = 0;
    reg [7:0] last_nc = 8'hff;
    reg [7:0] nc_by_frame [0:15];

    always @(posedge clk) begin
        if (u_frame.fcnt != fr) begin
            if (fr > 0) begin
                nc_by_frame[fr] = last_nc;
                $display("FRAME %0d  ncand=%0d  led=%b", fr, last_nc, led);
            end
            fr = u_frame.fcnt;
            nb = 0;
        end
        if (u_frame.ccl_valid && (nb < NBYTE)) begin
            bytes[nb] = u_frame.ccl_data;
            if (nb == 0) last_nc = u_frame.ccl_data;
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
        while ((u_frame.fcnt < NFRAME) && (guard < 80000000)) begin
            @(posedge clk);
            guard = guard + 1;
        end
        repeat (10) @(posedge clk);

        $display("----------------------------------------------");
        for (k = 1; k <= NFRAME; k = k + 1) begin
            $display("SUMMARY frame %0d : ncand = %0d", k, nc_by_frame[k]);
        end
        $display("----------------------------------------------");
        $display("last frame candidates:");
        for (k = 0; k < 5; k = k + 1) begin
            $display("CAND %0d: x=%0d y=%0d area=%0d peak=%0d",
                k,
                {bytes[1+k*7], bytes[2+k*7]},
                {bytes[3+k*7], bytes[4+k*7]},
                bytes[1+k*7+5],
                bytes[1+k*7+6]);
        end
        $finish;
    end

endmodule
