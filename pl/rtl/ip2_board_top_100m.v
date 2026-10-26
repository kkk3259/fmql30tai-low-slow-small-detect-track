// ============================================================================
// ip2_board_top_100m.v —— 100MHz 探针顶层（只用来测 100MHz 能不能收敛）
//
// 与 ip2_board_top 完全相同的电路，只把 DIV_SEL 设成 0（200MHz ÷ 2 = 100MHz）。
// 配套约束文件：board/board_lite_100m.fdc（-divide_by 2）
// 配套脚本    ：synth/board_ip2_100m.tcl
//
// 用途：跑一次 place/route 看 setup slack 是否转正；转正就能把工作频率从
//       50MHz 提到 100MHz（帧时间 5.0ms -> 2.5ms，加速 12x -> 23x）。
// ============================================================================
module ip2_board_top_100m (
    input  wire       clk_p,
    input  wire       clk_n,
    input  wire       rst_n,
    output wire [3:0] led
);
    ip2_board_top #(
        .DIV_SEL (0)             // 0 = 100MHz
    ) u_board (
        .clk_p (clk_p),
        .clk_n (clk_n),
        .rst_n (rst_n),
        .led   (led)
    );
endmodule
