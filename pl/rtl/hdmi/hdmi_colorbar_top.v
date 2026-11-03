// hdmi_colorbar_top.v  —  720p 彩条 HDMI 输出（纯 PL，不依赖 PS）
//
// 时钟链：板载 200 MHz 差分(C8/C7) -> MMCM VCO = 200 * 3.750 = 750 MHz
//         CLKOUT0 /10 = 75.0 MHz  (像素时钟)
//         CLKOUT1 /2  = 375  MHz  (5x，供 OSERDESE2)
//         CLKOUT2 /4  = 187.5 MHz (2.5x)
//
// 为什么是 75.0 而不是标准的 74.25 MHz：
//   720p60 标准像素时钟 74.25 MHz = 3^4 * 11 / 16，从 200 MHz 用 MMCM 的整数
//   乘除法无法精确得到（最接近 73.75，偏 0.67% 会黑屏）。75.0 MHz 时
//   1650 x 750 的帧结构刷新率为 60.6 Hz，绝大多数显示器可接受。
`timescale 1ns / 1ps

module hdmi_colorbar_top(
    input  wire       clk_p,
    input  wire       clk_n,
    output wire       HDMI_CLK_P,
    output wire       HDMI_CLK_N,
    output wire [2:0] HDMI_TX_P,
    output wire [2:0] HDMI_TX_N
);

    wire clk_ibuf;
    IBUFDS #(.DIFF_TERM("TRUE"), .IOSTANDARD("DIFF_SSTL15")) u_ibufds (
        .I(clk_p), .IB(clk_n), .O(clk_ibuf));

    wire clk_pix, clk_x5, clk_x25, clkfb, mmcm_locked;

    MMCME2_BASE #(
        .CLKIN1_PERIOD      (5.000),
        .DIVCLK_DIVIDE      (1),
        .CLKFBOUT_MULT_F    (3.750),    // VCO = 200 * 3.75 = 750 MHz
        .CLKOUT0_DIVIDE_F   (10.000),   // 75.0 MHz
        .CLKOUT1_DIVIDE     (2),        // 375  MHz
        .CLKOUT2_DIVIDE     (4),        // 187.5 MHz
        .CLKOUT0_DUTY_CYCLE (0.500),
        .CLKOUT1_DUTY_CYCLE (0.500),
        .CLKOUT2_DUTY_CYCLE (0.500)
    ) u_mmcm (
        .CLKIN1   (clk_ibuf),
        .CLKFBIN  (clkfb),
        .CLKFBOUT (clkfb),
        .CLKOUT0  (clk_pix),
        .CLKOUT1  (clk_x5),
        .CLKOUT2  (clk_x25),
        .CLKOUT3  (),
        .CLKOUT4  (),
        .CLKOUT5  (),
        .CLKOUT6  (),
        .CLKFBOUTB(),
        .CLKOUT0B (),
        .CLKOUT1B (),
        .CLKOUT2B (),
        .CLKOUT3B (),
        .CLKOUT4B (),
        .CLKOUT5B (),
        .CLKOUT6B (),
        .LOCKED   (mmcm_locked),
        .PWRDWN   (1'b0),
        .RST      (1'b0)
    );

    // 复位：等 MMCM 锁定后再放 16 个像素时钟
    reg [3:0] rst_cnt = 4'd0;
    always @(posedge clk_pix) begin
        if (!mmcm_locked)      rst_cnt <= 4'd0;
        else if (!rst_cnt[3])  rst_cnt <= rst_cnt + 1'b1;
    end
    wire rst = ~rst_cnt[3];

    wire       hs, vs, de;
    wire [7:0] rr, gg, bb;

    color_bar u_bar (
        .clk  (clk_pix),
        .rst  (rst),
        .hs   (hs),
        .vs   (vs),
        .de   (de),
        .rgb_r(rr),
        .rgb_g(gg),
        .rgb_b(bb)
    );

    wire       tmds_clk_p, tmds_clk_n;
    wire [2:0] tmds_p, tmds_n;

    uihdmitx #(.FAMILY("7SERIES")) u_hdmi (
        .RSTn_i        (~rst),
        .HS_i          (hs),
        .VS_i          (vs),
        .VDE_i         (de),
        .RGB_i         ({rr, gg, bb}),
        .PCLKX1_i      (clk_pix),
        .PCLKX2_5_i    (clk_x25),
        .PCLKX5_i      (clk_x5),
        .TMDS_TX_CLK_P (tmds_clk_p),
        .TMDS_TX_CLK_N (tmds_clk_n),
        .TMDS_TX_P     (tmds_p),
        .TMDS_TX_N     (tmds_n)
    );

    OBUFDS #(.IOSTANDARD("TMDS_33")) u_clk_obuf (
        .I(tmds_clk_p), .O(HDMI_CLK_P), .OB(HDMI_CLK_N));

    genvar i;
    generate
        for (i = 0; i < 3; i = i + 1) begin : g_obuf
            OBUFDS #(.IOSTANDARD("TMDS_33")) u_obuf (
                .I(tmds_p[i]), .O(HDMI_TX_P[i]), .OB(HDMI_TX_N[i]));
        end
    endgenerate

endmodule
