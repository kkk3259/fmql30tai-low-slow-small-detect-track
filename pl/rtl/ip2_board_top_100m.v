// ============================================================================
// ip2_board_top_100m.v —— 100MHz 探针顶层（只用来测 100MHz 能不能收敛）
//
// 【为什么不用 ip2_board_top 套一层】
//   Procise 的 .fdc 用 `-get_pins {u_bufg100/O}` 定位分频后的 BUFG。
//   如果在外面再包一层模块（u_board/u_bufg100/O），层次名就变了，
//   约束会报 `FDC_WARNING! cannot get pin {u_bufg100/O}` + `FDC_ERROR! No clock source found`
//   整个流程会停在 rtl_analyze。所以这里**把时钟产生电路复制到顶层**，保证
//   BUFG 实例名就是 u_bufg100（与 50MHz 版 board_lite.fdc 完全一致）。
//
// 与 ip2_board_top(DIV_SEL=1) 的唯一差别：分频取 div[0]（200MHz/2 = 100MHz）。
// 配套：pl/constr/board_lite_100m.fdc（-divide_by 2）、synth/board_ip2_100m.tcl
// ============================================================================
module ip2_board_top_100m (
    input  wire       clk_p,
    input  wire       clk_n,
    input  wire       rst_n,
    output wire [3:0] led
);
    wire clk200_raw;
    wire clk200;
    wire clk;

    // ---- 200MHz 差分时钟输入（C8/C7, DIFF_SSTL15）----
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
    reg [1:0] div = 2'd0;
    always @(posedge clk200) begin
        div <= div + 2'd1;
    end

    // 实例名必须叫 u_bufg100（.fdc 用 -get_pins {u_bufg100/O} 定位它）
    BUFG u_bufg100 (
        .I (div[0]),
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
