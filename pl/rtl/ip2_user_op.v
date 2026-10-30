//==============================================================================
// ip2_user_op.v —— 把 IP2 检测器接到 FMSH FPAI 平台的“自定义算子”接口
//
// 平台给自定义算子两个口（见 ai7030_edif_top.v）：
//   1) 寄存器口 itf_ra_*  : 32 位，awaddr 是“字序号”（不是字节地址），
//                          awready 恒 1；读有 1 拍延迟（arvalid→rvalid）
//   2) 数据口   itf_*     : 512 位宽，每拍 64 字节，地址 +64 递增
//
// 本模块做两件事：
//   A. 寄存器口  <-> 我们 ip2_axi_top 的 AXI-Lite 从口（6 位字地址）
//   B. 平台 512 位读 <-> 我们 ip2_axi_top 的 64 位 AXI 读主口（64 字节行缓存）
//
// 寄存器映射（平台字序号 index；PS 侧 byte addr = 0x400C0000 + 4*index）
//   0x00 W  CTRL         bit0 = start（写 1 启动一帧）
//   0x01 W  FRAME_ADDR   PL DDR 里帧数据的字节地址
//   0x02 R  STATUS       [7:0]=n_cand [30]=err [31]=done
//   0x03 R  VERSION      0x00010000
//   0x04 R  FRAME_ID
//   0x08~0x10 R          36 字节兼容视图（9 个字，byte0 = n_cand）
//   0x20 R  DONE         和 STATUS[31] 同义（兼容学长 demo 的地址）
//   0x77 W  任意写       软复位（兼容学长 demo）
//==============================================================================
`timescale 1ns / 1ps

module ip2_user_op #(
    parameter integer W = 640,
    parameter integer H = 360,
    parameter integer SE = 21,
    parameter integer MAX_CAND = 64
) (
    // ---------------- 平台寄存器口（gp_clk 域） ----------------
    input  wire [31:0] itf_ra_awaddr,
    input  wire [31:0] itf_ra_awdata,
    input  wire        itf_ra_awvalid,
    output wire        itf_ra_awready,
    input  wire [31:0] itf_ra_araddr,
    input  wire        itf_ra_arvalid,
    output wire        itf_ra_arready,
    output wire [31:0] itf_ra_rdata,
    output wire        itf_ra_rvalid,
    input  wire        itf_ra_rready,

    // ---------------- 平台数据口（hp_clk 域，512 位） ----------------
    output wire [31:0]  itf_awaddr,
    output wire [511:0] itf_awdata,
    output wire         itf_awvalid,
    input  wire         itf_awready,
    output wire [31:0]  itf_araddr,
    output wire         itf_arvalid,
    input  wire         itf_arready,
    input  wire [511:0] itf_rdata,
    input  wire         itf_rvalid,
    output wire         itf_rready,

    output wire [1:0]  led,

    // ---------------- 时钟复位 ----------------
    input  wire        clk,          // hp_clk
    input  wire        ra_clk,       // gp_clk
    input  wire        rst_n,        // ~hp_clk_rst
    input  wire        ra_rst_n      // ~gp_clk_rst
);

    //================= 所有内部 net 先声明 =================
    // AXI-Lite 主（由本模块驱动我们检测器的从口）
    wire        axi_awvalid, axi_awready;
    wire        axi_wvalid,  axi_wready;
    wire [1:0]  axi_bresp;
    wire        axi_bvalid,  axi_bready;
    wire        axi_arvalid, axi_arready;
    wire [31:0] axi_rdata;
    wire [1:0]  axi_rresp;
    wire        axi_rvalid,  axi_rready;

    // AXI 读主（检测器 -> 本模块的转换逻辑）
    wire [31:0] m_araddr;
    wire [7:0]  m_arlen;
    wire [2:0]  m_arsize;
    wire [1:0]  m_arburst;
    wire        m_arvalid, m_arready;
    wire [63:0] m_rdata;
    wire        m_rlast, m_rvalid, m_rready;

    // AXI 写主（本设计不使用，悬空）
    wire [31:0] m_awaddr;
    wire [7:0]  m_awlen;
    wire [2:0]  m_awsize;
    wire [1:0]  m_awburst;
    wire        m_awvalid;
    wire [63:0] m_wdata;
    wire [7:0]  m_wstrb;
    wire        m_wlast, m_wvalid, m_bready;

    wire [3:0]  led_i;

    // 平台字节地址 -> 我们的 6 位字节地址：低 6 位原样映射；
    // 平台的 COMPUTE_DONE（字节 0x80）映射到我们的 STATUS（0x0C），读回只取 bit1(done)
    wire done_sel_w = (itf_ra_awaddr[11:0] == 12'h080);
    wire done_sel_r = (itf_ra_araddr[11:0] == 12'h080);
    wire [5:0] ra_word = done_sel_w ? 6'h0C : itf_ra_awaddr[5:0];
    wire [5:0] rd_word = done_sel_r ? 6'h0C : itf_ra_araddr[5:0];

    //==================================================================
    // A. 寄存器口 -> AXI-Lite 写
    //==================================================================
    reg  [5:0]  aw_addr_q;
    reg  [31:0] aw_data_q;
    reg         aw_pend;
    reg         w_pend;
    reg         b_wait;

    assign itf_ra_awready = ~aw_pend & ~b_wait;
    assign axi_awvalid    = aw_pend;
    assign axi_wvalid     = w_pend;
    assign axi_bready     = b_wait;

    always @(posedge ra_clk or negedge ra_rst_n) begin
        if (!ra_rst_n) begin
            aw_pend <= 1'b0; w_pend <= 1'b0; b_wait <= 1'b0;
            aw_addr_q <= 6'd0; aw_data_q <= 32'd0;
        end else begin
            if (itf_ra_awvalid && itf_ra_awready) begin
                aw_addr_q <= ra_word;
                aw_data_q <= itf_ra_awdata;
                aw_pend   <= 1'b1;
                w_pend    <= 1'b1;
            end else begin
                if (axi_awvalid && axi_awready) aw_pend <= 1'b0;
                if (axi_wvalid  && axi_wready ) w_pend  <= 1'b0;
            end
            if (axi_bvalid)                b_wait <= 1'b1;
            else if (b_wait && axi_bready) b_wait <= 1'b0;
        end
    end

    //==================================================================
    // B. 寄存器口 -> AXI-Lite 读
    //==================================================================
    reg  [5:0]  ar_addr_q;
    reg         ar_pend;
    reg         r_wait;
    reg         rd_is_done;

    assign itf_ra_arready = ~ar_pend & ~r_wait;
    assign axi_arvalid    = ar_pend;
    assign axi_rready     = r_wait;
    assign itf_ra_rdata   = rd_is_done ? {31'b0, axi_rdata[1]} : axi_rdata;
    assign itf_ra_rvalid  = r_wait;

    always @(posedge ra_clk or negedge ra_rst_n) begin
        if (!ra_rst_n) begin
            ar_pend <= 1'b0; r_wait <= 1'b0; ar_addr_q <= 6'd0; rd_is_done <= 1'b0;
        end else begin
            if (itf_ra_arvalid && itf_ra_arready) begin
                ar_addr_q <= rd_word;
                rd_is_done <= done_sel_r;
                ar_pend   <= 1'b1;
            end else if (axi_arvalid && axi_arready) begin
                ar_pend   <= 1'b0;
            end
            if (axi_rvalid)                r_wait <= 1'b1;
            else if (r_wait && axi_rready) r_wait <= 1'b0;
        end
    end

    //==================================================================
    // C. 平台 512 位读 -> 我们的 64 位 AXI 读主口
    //==================================================================
    reg  [511:0] line_data;
    reg  [25:0]  line_tag;
    reg          line_valid;

    reg  [31:0]  bus_addr;
    reg  [7:0]   bus_left;
    reg          bus_active;

    reg  [31:0]  plat_araddr_q;
    reg          plat_arvalid_q;
    reg          fetch_busy;

    wire [25:0] want_tag  = bus_addr[31:6];
    wire [2:0]  want_word = bus_addr[5:3];
    wire        hit       = line_valid && (line_tag == want_tag);
    wire [63:0] line_word = line_data[{want_word, 3'b000} +: 64];

    assign itf_araddr  = plat_araddr_q;
    assign itf_arvalid = plat_arvalid_q;
    assign itf_rready  = fetch_busy;

    assign m_arready = ~bus_active & ~fetch_busy & ~plat_arvalid_q;
    assign m_rvalid  = bus_active & hit;
    assign m_rdata   = line_word;
    assign m_rlast   = (bus_left == 8'd0);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            line_data <= 512'd0; line_tag <= 26'd0; line_valid <= 1'b0;
            bus_addr <= 32'd0; bus_left <= 8'd0; bus_active <= 1'b0;
            plat_araddr_q <= 32'd0; plat_arvalid_q <= 1'b0; fetch_busy <= 1'b0;
        end else begin
            // 接主口突发请求
            if (m_arvalid && m_arready) begin
                bus_addr   <= m_araddr;
                bus_left   <= m_arlen;
                bus_active <= 1'b1;
            end

            // 平台读发起/撤销
            if (plat_arvalid_q && itf_arready) plat_arvalid_q <= 1'b0;

            if (bus_active && !hit && !fetch_busy && !plat_arvalid_q) begin
                plat_araddr_q  <= {want_tag, 6'b0};
                plat_arvalid_q <= 1'b1;
                fetch_busy     <= 1'b1;
            end

            // 平台读返回：填行缓存
            if (fetch_busy && itf_rvalid) begin
                line_data  <= itf_rdata;
                line_tag   <= plat_araddr_q[31:6];
                line_valid <= 1'b1;
                fetch_busy <= 1'b0;
            end

            // 回数据给主口
            if (m_rvalid && m_rready) begin
                if (bus_left == 8'd0) begin
                    bus_active <= 1'b0;
                end else begin
                    bus_left <= bus_left - 8'd1;
                    bus_addr <= bus_addr + 32'd8;
                end
            end
        end
    end

    //==================================================================
    // D. 检测器本体
    //==================================================================
    ip2_axi_top #(
        .W        (W),
        .H        (H),
        .SE       (SE),
        .MAX_CAND (MAX_CAND)
    ) u_ip2 (
        .clk           (clk),
        .rst_n         (rst_n),
        .led           (led_i),

        .s_axi_awaddr  (aw_addr_q),
        .s_axi_awvalid (axi_awvalid),
        .s_axi_awready (axi_awready),
        .s_axi_wdata   (aw_data_q),
        .s_axi_wstrb   (4'hF),
        .s_axi_wvalid  (axi_wvalid),
        .s_axi_wready  (axi_wready),
        .s_axi_bresp   (axi_bresp),
        .s_axi_bvalid  (axi_bvalid),
        .s_axi_bready  (axi_bready),

        .s_axi_araddr  (ar_addr_q),
        .s_axi_arvalid (axi_arvalid),
        .s_axi_arready (axi_arready),
        .s_axi_rdata   (axi_rdata),
        .s_axi_rresp   (axi_rresp),
        .s_axi_rvalid  (axi_rvalid),
        .s_axi_rready  (axi_rready),

        .m_axi_araddr  (m_araddr),
        .m_axi_arlen   (m_arlen),
        .m_axi_arsize  (m_arsize),
        .m_axi_arburst (m_arburst),
        .m_axi_arvalid (m_arvalid),
        .m_axi_arready (m_arready),
        .m_axi_rdata   (m_rdata),
        .m_axi_rresp   (2'b00),
        .m_axi_rlast   (m_rlast),
        .m_axi_rvalid  (m_rvalid),
        .m_axi_rready  (m_rready),

        .m_axi_awaddr  (m_awaddr),
        .m_axi_awlen   (m_awlen),
        .m_axi_awsize  (m_awsize),
        .m_axi_awburst (m_awburst),
        .m_axi_awvalid (m_awvalid),
        .m_axi_awready (1'b0),
        .m_axi_wdata   (m_wdata),
        .m_axi_wstrb   (m_wstrb),
        .m_axi_wlast   (m_wlast),
        .m_axi_wvalid  (m_wvalid),
        .m_axi_wready  (1'b0),
        .m_axi_bresp   (2'b00),
        .m_axi_bvalid  (1'b0),
        .m_axi_bready  (m_bready)
    );

    assign itf_awaddr  = 32'd0;
    assign itf_awdata  = 512'd0;
    assign itf_awvalid = 1'b0;
    assign led         = led_i[1:0];

endmodule
