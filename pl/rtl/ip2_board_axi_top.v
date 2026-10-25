// ============================================================================
// ip2_board_axi_top.v —— 悟净 Lite 板级顶层（正式版：AXI 接 PS）
//
// 与 ip2_board_top.v（自测版，内部图案 + LED）的区别：
//   本文件把 IP2 全链包成 AXI 从机（PS 读写的控制寄存器）+ AXI 主机
//   （从 DDR 读 640x360 帧、把 36 字节候选表写回 DDR），供 PS 侧
//   pl_link.py 直接调用（寄存器/地址约定见 docs/14-PS-PL接口约定.md）。
//
// 时钟：板载 PL 差分晶振 200MHz，P=C8 / N=C7，IOSTANDARD DIFF_SSTL15
//       IBUFDS -> BUFG(200M) -> 2 分频 -> BUFG(100M) 作为工作时钟，
//       同时作为 AXI 时钟（PS 侧 HP 口最高 100MHz，正好匹配）
// 复位：rst_n 接 F8（PL_KEY1，按下为低）
// LED ：J1/M6/H7/J8 = led[0..3]
//       led[0]   = 心跳（整帧完成翻转）
//       led[3:1] = 本帧候选数（饱和 7）
// ============================================================================
module ip2_board_axi_top #(
    parameter W = 640,
    parameter H = 360,
    parameter MAX_CAND = 5,
    parameter [31:0] DEF_FRAME_ADDR  = 32'h3010_0000,
    parameter [31:0] DEF_RESULT_ADDR = 32'h3100_0000
) (
    input  wire        clk_p,
    input  wire        clk_n,
    input  wire        rst_n,
    output wire [3:0]  led,

    // ---- AXI4-Lite 从机：控制/状态寄存器（PS -> PL）----
    input  wire [5:0]  s_axi_awaddr,
    input  wire        s_axi_awvalid,
    output wire        s_axi_awready,
    input  wire [31:0] s_axi_wdata,
    input  wire [3:0]  s_axi_wstrb,
    input  wire        s_axi_wvalid,
    output wire        s_axi_wready,
    output wire [1:0]  s_axi_bresp,
    output wire        s_axi_bvalid,
    input  wire        s_axi_bready,
    input  wire [5:0]  s_axi_araddr,
    input  wire        s_axi_arvalid,
    output wire        s_axi_arready,
    output wire [31:0] s_axi_rdata,
    output wire [1:0]  s_axi_rresp,
    output wire        s_axi_rvalid,
    input  wire        s_axi_rready,

    // ---- AXI4 主机：读帧（DDR -> PL）----
    output wire [31:0] m_axi_araddr,
    output wire [7:0]  m_axi_arlen,
    output wire [2:0]  m_axi_arsize,
    output wire [1:0]  m_axi_arburst,
    output wire        m_axi_arvalid,
    input  wire        m_axi_arready,
    input  wire [63:0] m_axi_rdata,
    input  wire [1:0]  m_axi_rresp,
    input  wire        m_axi_rlast,
    input  wire        m_axi_rvalid,
    output wire        m_axi_rready,

    // ---- AXI4 主机：写结果（PL -> DDR）----
    output wire [31:0] m_axi_awaddr,
    output wire [7:0]  m_axi_awlen,
    output wire [2:0]  m_axi_awsize,
    output wire [1:0]  m_axi_awburst,
    output wire        m_axi_awvalid,
    input  wire        m_axi_awready,
    output wire [63:0] m_axi_wdata,
    output wire [7:0]  m_axi_wstrb,
    output wire        m_axi_wlast,
    output wire        m_axi_wvalid,
    input  wire        m_axi_wready,
    input  wire [1:0]  m_axi_bresp,
    input  wire        m_axi_bvalid,
    output wire        m_axi_bready
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

    // ---- AXI 版全链 ----
    ip2_axi_top #(
        .W(W), .H(H), .MAX_CAND(MAX_CAND),
        .DEF_FRAME_ADDR (DEF_FRAME_ADDR),
        .DEF_RESULT_ADDR(DEF_RESULT_ADDR)
    ) u_axi (
        .clk   (clk),
        .rst_n (rst_n),
        .led   (led),

        .s_axi_awaddr (s_axi_awaddr),
        .s_axi_awvalid(s_axi_awvalid),
        .s_axi_awready(s_axi_awready),
        .s_axi_wdata  (s_axi_wdata),
        .s_axi_wstrb  (s_axi_wstrb),
        .s_axi_wvalid (s_axi_wvalid),
        .s_axi_wready (s_axi_wready),
        .s_axi_bresp  (s_axi_bresp),
        .s_axi_bvalid (s_axi_bvalid),
        .s_axi_bready (s_axi_bready),
        .s_axi_araddr (s_axi_araddr),
        .s_axi_arvalid(s_axi_arvalid),
        .s_axi_arready(s_axi_arready),
        .s_axi_rdata  (s_axi_rdata),
        .s_axi_rresp  (s_axi_rresp),
        .s_axi_rvalid (s_axi_rvalid),
        .s_axi_rready (s_axi_rready),

        .m_axi_araddr (m_axi_araddr),
        .m_axi_arlen  (m_axi_arlen),
        .m_axi_arsize (m_axi_arsize),
        .m_axi_arburst(m_axi_arburst),
        .m_axi_arvalid(m_axi_arvalid),
        .m_axi_arready(m_axi_arready),
        .m_axi_rdata  (m_axi_rdata),
        .m_axi_rresp  (m_axi_rresp),
        .m_axi_rlast  (m_axi_rlast),
        .m_axi_rvalid (m_axi_rvalid),
        .m_axi_rready (m_axi_rready),

        .m_axi_awaddr (m_axi_awaddr),
        .m_axi_awlen  (m_axi_awlen),
        .m_axi_awsize (m_axi_awsize),
        .m_axi_awburst(m_axi_awburst),
        .m_axi_awvalid(m_axi_awvalid),
        .m_axi_awready(m_axi_awready),
        .m_axi_wdata  (m_axi_wdata),
        .m_axi_wstrb  (m_axi_wstrb),
        .m_axi_wlast  (m_axi_wlast),
        .m_axi_wvalid (m_axi_wvalid),
        .m_axi_wready (m_axi_wready),
        .m_axi_bresp  (m_axi_bresp),
        .m_axi_bvalid (m_axi_bvalid),
        .m_axi_bready (m_axi_bready)
    );

endmodule
