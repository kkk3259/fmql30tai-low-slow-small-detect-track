// ============================================================================
// ip2_board_top.v —— 悟净 Lite 板级顶层（上板用一个文件搞定）
//
// 时钟：板载 PL 差分晶振 200MHz，P=C8 / N=C7（官方 fpai_demo 工程
//       constrs_1/impl_constraints.xdc 里确认；IOSTANDARD = DIFF_SSTL15）
//       IBUFDS -> BUFG -> 200MHz 主时钟；再分频 -> BUFG -> 工作时钟
//
// 工作频率由参数 DIV_SEL 选择：
//       DIV_SEL = 0 -> div[0] = 100MHz（需在 .fdc 里写 -divide_by 2）
//       DIV_SEL = 1 -> div[1] =  50MHz（默认；2026-10-26 已上板验证，setup +0.041ns）
//       DIV_SEL = 2 -> div[2] =  25MHz（时序余量不足时的保险档，-divide_by 8）
//   单帧拍数约 248,000：100MHz→2.5ms、50MHz→5.0ms、25MHz→9.9ms
//
// 复位：rst_n 接 F8（板上 PL_KEY1，按下为低），内部再做 32 拍同步 + 上电计数
//
// 输出：LED J1/M6/H7/J8 = led[0..3]（BANK13，LVCMOS15）
//       led[0]   = 心跳（每 128 帧翻转，50MHz 下约 1.28s 一周期）
//       led[3:1] = 本帧候选个数（饱和到 7，正常自测图案应为 4 → 100）
// ============================================================================
module ip2_board_top #(
    parameter DIV_SEL = 1        // 0=100MHz  1=50MHz  2=25MHz
) (
    input  wire       clk_p,
    input  wire       clk_n,
    input  wire       rst_n,
    output wire [3:0] led
);
    wire clk200_raw;
    wire clk200;
    wire clk_sel;
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

    // ---- 分频：div[0]=100MHz / div[1]=50MHz / div[2]=25MHz ----
    // 【2026-10-26】100MHz 版当时 setup 差 -7.385ns（两条最长路径：CCL 求根 391 级、
    //   重心除法 104 级）。这两条路径已拆成多周期后，50MHz 收敛（+0.041ns）；
    //   100MHz 尚未重新验证，用 DIV_SEL=0 可一键切回去试。
    reg [2:0] div = 3'd0;
    always @(posedge clk200) begin
        div <= div + 3'd1;
    end

    reg clk_sel_r;
    always @(*) begin
        case (DIV_SEL)
            2'd0:    clk_sel_r = div[0];
            2'd2:    clk_sel_r = div[2];
            default: clk_sel_r = div[1];
        endcase
    end
    assign clk_sel = clk_sel_r;

    // 实例名保持 u_bufg100 不变（.fdc 里的 create_generated_clock 用 -get_pins {u_bufg100/O}
    // 定位这个 BUFG；改名会让已有约束失效，名字只是历史遗留）
    BUFG u_bufg100 (
        .I (clk_sel),
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
