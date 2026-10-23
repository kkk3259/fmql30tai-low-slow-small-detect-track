// ============================================================================
// ip2_board_top.v —— 悟净 Lite 板级顶层（上板用一个文件搞定）
//
// 时钟：板载 PL 差分晶振 200MHz，P=C8 / N=C7（官方 fpai_demo 工程
//       constrs_1/impl_constraints.xdc 里确认；IOSTANDARD = DIFF_SSTL15）
//       IBUFDS -> BUFG -> 200MHz 主时钟；再 2 分频 -> BUFG -> 100MHz 工作时钟
//       （IP2 全链按 100MHz 交付，640x360 约 2.6ms/帧）
//
// 复位：rst_n 接 F8（板上 PL_KEY1，按下为低），内部再做 32 拍同步 + 上电计数
//
// 输出：LED J1/M6/H7/J8 = led[0..3]（BANK13，LVCMOS15）
//       led[0]   = 心跳（每 128 帧翻转）
//       led[3:1] = 本帧候选个数（饱和到 7，正常自测图案应为 4 → 100）
// ============================================================================
module ip2_board_top (
    input  wire       clk_p,
    input  wire       clk_n,
    input  wire       rst_n,
    output wire [3:0] led
);
    wire clk200_raw;
    wire clk200;
    wire clkdiv;
    wire clk;

    // ---- 200MHz 差分时钟输入 ----
    IBUFDS u_ibufds (
        .O  (clk200_raw),
        .I  (clk_p),
        .IB (clk_n)
    );

    BUFG u_bufg200 (
        .I (clk200_raw),
        .O (clk200)
    );

    // ---- 200MHz / 2 = 100MHz（50% 占空比）----
    reg div = 1'b0;
    always @(posedge clk200) begin
        div <= ~div;
    end

    BUFG u_bufg100 (
        .I (div),
        .O (clk)
    );

    // ---- 帧级顶层（图案 -> IP2 全链 -> LED）----
    ip2_frame_top #(
        .W        (640),
        .H        (360),
        .MAX_CAND (5)
    ) u_frame (
        .clk   (clk),
        .rst_n (rst_n),
        .led   (led)
    );

endmodule
