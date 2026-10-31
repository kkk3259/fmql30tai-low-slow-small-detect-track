//=============================================================================
// ip2_user_op.v —— 把自研检测器（ip2_axi_top）接到 FMSH 三域平台的“自定义算子”接口
//
// 平台接口：
//   1) 寄存器口 itf_ra_* : 32 位，字节地址（ra_clk = gp_clk = 50 MHz）
//   2) 数据口   itf_*    : 512 位，每拍 64 字节，地址 +64（clk = hp_clk = 200 MHz）
//
// 【v2 关键改动：把检测器核降到 50 MHz】
//   v1 把核直接接在 hp_clk(200 MHz) 上，实测 WNS = -11.938 ns
//   （最差路径 u_cfar/wpa_reg[2]_replica -> q1_ws2_reg[25]/D，数据路径 16.8 ns），
//   核在 200 MHz 下算错 -> FSM 卡死 -> 占死 PL-DDR 读通道 -> 整板 AXI 挂死。
//   v2：core_clk = clk/4 = 50 MHz（同源分频），核 + AXI 主口 + 行缓存都在 core_clk；
//       两个时钟域之间一律用 toggle 握手（数据先稳定、再翻转），不依赖异步 FIFO。
//=============================================================================
`timescale 1ns / 1ps

module ip2_user_op #(
    parameter W        = 640,
    parameter H        = 360,
    parameter SE       = 5,
    parameter MAX_CAND = 16
) (
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

    input  wire        clk,          // hp_clk 200 MHz
    input  wire        ra_clk,       // gp_clk  50 MHz
    input  wire        rst_n,
    input  wire        ra_rst_n
);

    //=========================================================================
    // 0. core_clk = clk / 4 = 50 MHz
    //=========================================================================
    reg [1:0] div_cnt;
    reg       core_clk;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            div_cnt  <= 2'd0;
            core_clk <= 1'b0;
        end else if (div_cnt == 2'd1) begin
            div_cnt  <= 2'd0;
            core_clk <= ~core_clk;
        end else begin
            div_cnt <= div_cnt + 2'd1;
        end
    end

    reg [1:0] core_rst_sync;
    always @(posedge core_clk or negedge rst_n) begin
        if (!rst_n) core_rst_sync <= 2'b00;
        else        core_rst_sync <= {core_rst_sync[0], 1'b1};
    end
    wire core_rst_n = core_rst_sync[1];

    //=========================================================================
    // 1. 跨域所有 toggle / 数据寄存器声明
    //=========================================================================
    reg        wr_t;            // ra   -> core（写请求）
    reg [5:0]  wr_addr_q;
    reg [31:0] wr_data_q;
    reg        wr_ack_t;        // core -> ra  （写完成）

    reg        rd_t;            // ra   -> core（读请求）
    reg [5:0]  rd_addr_q;
    reg        rd_is_done_q;
    reg        rd_ack_t;        // core -> ra  （读完成）
    reg [31:0] rd_data_c;       // core 域锁存的读数据

    reg        lin_req_t;       // core -> clk （行读请求）
    reg [31:0] lin_addr_q;
    reg        lin_rdy_t;       // clk  -> core（行数据就绪）
    reg [511:0] lin_data_c;     // clk 域锁存的 512 位行

    //=========================================================================
    // 2. 同步器：2FF + 边沿检测
    //=========================================================================
    reg [2:0] s_wr_req, s_rd_req, s_lin_rdy, s_lin_req, s_wr_ack, s_rd_ack;

    always @(posedge core_clk or negedge core_rst_n)
        if (!core_rst_n) s_wr_req <= 3'd0; else s_wr_req <= {s_wr_req[1:0], wr_t};
    always @(posedge core_clk or negedge core_rst_n)
        if (!core_rst_n) s_rd_req <= 3'd0; else s_rd_req <= {s_rd_req[1:0], rd_t};
    always @(posedge core_clk or negedge core_rst_n)
        if (!core_rst_n) s_lin_rdy <= 3'd0; else s_lin_rdy <= {s_lin_rdy[1:0], lin_rdy_t};

    always @(posedge ra_clk or negedge ra_rst_n)
        if (!ra_rst_n) s_wr_ack <= 3'd0; else s_wr_ack <= {s_wr_ack[1:0], wr_ack_t};
    always @(posedge ra_clk or negedge ra_rst_n)
        if (!ra_rst_n) s_rd_ack <= 3'd0; else s_rd_ack <= {s_rd_ack[1:0], rd_ack_t};

    always @(posedge clk or negedge rst_n)
        if (!rst_n) s_lin_req <= 3'd0; else s_lin_req <= {s_lin_req[1:0], lin_req_t};

    wire wr_req_ev  = s_wr_req[2]  ^ s_wr_req[1];
    wire rd_req_ev  = s_rd_req[2]  ^ s_rd_req[1];
    wire lin_rdy_ev = s_lin_rdy[2] ^ s_lin_rdy[1];
    wire lin_req_ev = s_lin_req[2] ^ s_lin_req[1];
    wire wr_ack_ev  = s_wr_ack[2]  ^ s_wr_ack[1];
    wire rd_ack_ev  = s_rd_ack[2]  ^ s_rd_ack[1];

    //=========================================================================
    // 3. 寄存器口（ra_clk 域）
    //=========================================================================
    wire done_sel_w = (itf_ra_awaddr[11:0] == 12'h080);
    wire done_sel_r = (itf_ra_araddr[11:0] == 12'h080);
    // 调试窗口：字节地址 0x90/0x94/0x98/0x9C 读内部计数器（工程调试用，不影响功能）
    wire dbg_sel_r  = (itf_ra_araddr[11:4] == 8'h09);
    // 逻辑分析仪窗口：0xA0 写索引 / 0xA4 读数据 / 0xA8 状态 / 0xAC 清（读 0xA0..0xAF 同一组）
    wire la_sel     = (itf_ra_araddr[11:4] == 8'h0A);
    reg  [31:0] dbg_ar, dbg_rv, dbg_wd;   // 平台口调试计数器（在 clk 域自增，见第 5 节）
    wire [31:0] dbg_stat;                 // 平台口状态快照（见第 5 节）
    wire [31:0] la_rdata;                 // 逻辑分析仪读数据（见第 6 节）
    wire [31:0] la_status;                // {frozen, trig[3:0], wp[9:0]}
    reg  [7:0]  la_raddr;                 // 读地址（ra 域）
    wire [5:0] ra_word = done_sel_w ? 6'h0C : itf_ra_awaddr[5:0];
    wire [5:0] rd_word = done_sel_r ? 6'h0C : itf_ra_araddr[5:0];

    reg        wr_busy, rd_busy;
    reg [31:0] rd_data_q;
    reg        rvalid_r;
    reg [11:0] rd_addr12_q;      // 读地址快照（用于调试窗口选择）
    reg [11:0] rd_tmo;           // 读超时计数（防 PS 被挂死）

    assign itf_ra_awready = ~wr_busy;
    assign itf_ra_arready = ~rd_busy;
    assign itf_ra_rvalid  = rvalid_r;
    wire [31:0] dbg_word = (rd_addr12_q[3:2] == 2'd0) ? dbg_ar :
                           (rd_addr12_q[3:2] == 2'd1) ? dbg_rv :
                           (rd_addr12_q[3:2] == 2'd2) ? dbg_wd : dbg_stat;
    wire        dbg_sel_q = (rd_addr12_q[11:4] == 8'h09);
    wire        la_sel_q  = (rd_addr12_q[11:4] == 8'h0A);
    assign itf_ra_rdata   = rd_is_done_q ? {31'b0, rd_data_q[1]} :
                            dbg_sel_q    ? dbg_word :
                            la_sel_q     ? ((rd_addr12_q[3:2] == 2'd0) ? la_rdata :
                                            (rd_addr12_q[3:2] == 2'd2) ? la_status : 32'd0) :
                            rd_data_q;

    always @(posedge ra_clk or negedge ra_rst_n) begin
        if (!ra_rst_n) begin
            wr_t <= 1'b0; wr_addr_q <= 6'd0; wr_data_q <= 32'd0; wr_busy <= 1'b0;
        end else begin
            if (wr_ack_ev) wr_busy <= 1'b0;
            if (itf_ra_awvalid && !wr_busy) begin
                wr_addr_q <= ra_word;
                wr_data_q <= itf_ra_awdata;
                wr_t      <= ~wr_t;
                wr_busy   <= 1'b1;
            end
        end
    end

    //-------------------------------------------------------------------------
    // 3b. 逻辑分析仪写口（ra_clk 域）：0xA0 写索引 / 0xAC 清空
    //-------------------------------------------------------------------------
    reg la_clr_t;
    always @(posedge ra_clk or negedge ra_rst_n) begin
        if (!ra_rst_n) begin
            la_raddr   <= 8'd0;
            la_clr_t   <= 1'b0;
        end else begin
            if (itf_ra_awvalid && itf_ra_awready) begin
                if (itf_ra_awaddr[11:4] == 8'h0A && itf_ra_awaddr[3:2] == 2'd0)
                    la_raddr <= itf_ra_awdata[7:0];
                if (itf_ra_awaddr[11:0] == 12'h0AC)
                    la_clr_t <= ~la_clr_t;
            end
        end
    end

    always @(posedge ra_clk or negedge ra_rst_n) begin
        if (!ra_rst_n) begin
            rd_t <= 1'b0; rd_addr_q <= 6'd0; rd_is_done_q <= 1'b0; rd_busy <= 1'b0;
            rd_data_q <= 32'd0; rvalid_r <= 1'b0; rd_tmo <= 12'd0;
        end else begin
            // 超时保护：读请求若在 N 个 ra 拍内拿不到核的回应，强制返回 0xDEADBEEF。
            // 目的：即使核（clk 域）死掉，PS 侧也绝不能被挂住——否则整板锁死只能断电。
            if (rd_busy && !rd_ack_ev) begin
                if (rd_tmo != 12'hFFF) rd_tmo <= rd_tmo + 12'd1;
                else begin
                    rd_busy   <= 1'b0;
                    rd_data_q <= 32'hDEAD_BEEF;
                    rvalid_r  <= 1'b1;
                    rd_tmo    <= 12'd0;
                end
            end
            if (rd_ack_ev) begin
                rd_busy   <= 1'b0;
                rd_data_q <= rd_data_c;
                rvalid_r  <= 1'b1;
                rd_tmo    <= 12'd0;
            end else if (rvalid_r) begin
                rvalid_r  <= 1'b0;
            end
            if (itf_ra_arvalid && !rd_busy) begin
                rd_addr_q    <= rd_word;
                rd_addr12_q  <= itf_ra_araddr[11:0];
                rd_is_done_q <= done_sel_r;
                rd_t         <= ~rd_t;
                rd_busy      <= 1'b1;
                rd_tmo       <= 12'd0;
            end
        end
    end

    //=========================================================================
    // 4. AXI-Lite 主侧 + 检测器（core_clk 域）
    //=========================================================================
    reg        axi_awvalid_r, axi_wvalid_r, axi_bready_r, aw_done_r, w_done_r;
    reg        axi_arvalid_r, axi_rready_r;
    reg [5:0]  aw_addr_c, ar_addr_c;
    reg [31:0] aw_data_c;

    wire        axi_awready, axi_wready, axi_bvalid, axi_arready, axi_rvalid;
    wire [31:0] axi_rdata;
    wire [1:0]  axi_bresp, axi_rresp;

    wire [31:0] m_araddr;
    wire [7:0]  m_arlen;
    wire [2:0]  m_arsize;
    wire [1:0]  m_arburst;
    wire        m_arvalid, m_arready;
    wire [63:0] m_rdata;
    wire        m_rlast, m_rvalid, m_rready;
    wire [31:0] m_awaddr;
    wire [7:0]  m_awlen;
    wire [2:0]  m_awsize;
    wire [1:0]  m_awburst;
    wire        m_awvalid, m_wvalid, m_wlast, m_bready;
    wire [63:0] m_wdata;
    wire [7:0]  m_wstrb;

    reg [511:0] line_data;
    reg [25:0]  line_tag;
    reg         line_valid;
    reg [31:0]  bus_addr;
    reg [7:0]   bus_left;
    reg         bus_active;
    reg         lin_pend;
    reg [9:0]   pend_wd;

    wire [25:0] want_tag  = bus_addr[31:6];
    wire [2:0]  want_word = bus_addr[5:3];
    wire        hit       = line_valid && (line_tag == want_tag);
    wire [63:0] line_word = line_data[{want_word, 3'b000} +: 64];

    assign m_arready = ~bus_active & ~lin_pend;
    assign m_rvalid  = bus_active & hit;
    assign m_rdata   = line_word;
    assign m_rlast   = (bus_left == 8'd0);

    always @(posedge core_clk or negedge core_rst_n) begin
        if (!core_rst_n) begin
            axi_awvalid_r <= 1'b0; axi_wvalid_r <= 1'b0; axi_bready_r <= 1'b0;
            aw_done_r <= 1'b0; w_done_r <= 1'b0;
            axi_arvalid_r <= 1'b0; axi_rready_r <= 1'b0;
            aw_addr_c <= 6'd0; aw_data_c <= 32'd0; ar_addr_c <= 6'd0;
            wr_ack_t <= 1'b0; rd_ack_t <= 1'b0; rd_data_c <= 32'd0;
            line_data <= 512'd0; line_tag <= 26'd0; line_valid <= 1'b0;
            bus_addr <= 32'd0; bus_left <= 8'd0; bus_active <= 1'b0;
            lin_req_t <= 1'b0; lin_addr_q <= 32'd0; lin_pend <= 1'b0;
            pend_wd <= 10'd0;
        end else begin
            // ---- 写请求 ----
            if (wr_req_ev) begin
                aw_addr_c     <= wr_addr_q;
                aw_data_c     <= wr_data_q;
                axi_awvalid_r <= 1'b1;
                axi_wvalid_r  <= 1'b1;
            end
            if (axi_awvalid_r && axi_awready) begin
                axi_awvalid_r <= 1'b0;
                aw_done_r     <= 1'b1;
            end
            if (axi_wvalid_r  && axi_wready ) begin
                axi_wvalid_r  <= 1'b0;
                w_done_r      <= 1'b1;
            end
            if (aw_done_r && w_done_r) axi_bready_r <= 1'b1;
            if (axi_bvalid && axi_bready_r) begin
                axi_bready_r <= 1'b0;
                aw_done_r    <= 1'b0;
                w_done_r     <= 1'b0;
                wr_ack_t     <= ~wr_ack_t;
            end

            // ---- 读请求 ----
            if (rd_req_ev) begin
                ar_addr_c     <= rd_addr_q;
                axi_arvalid_r <= 1'b1;
            end
            if (axi_arvalid_r && axi_arready) begin
                axi_arvalid_r <= 1'b0;
                axi_rready_r  <= 1'b1;
            end
            if (axi_rvalid && axi_rready_r) begin
                rd_data_c    <= axi_rdata;
                axi_rready_r <= 1'b0;
                rd_ack_t     <= ~rd_ack_t;
            end

            // ---- 行数据返回 ----
            if (lin_rdy_ev) begin
                line_data  <= lin_data_c;
                line_tag   <= lin_addr_q[31:6];
                line_valid <= 1'b1;
                lin_pend   <= 1'b0;
            end

            // ---- 64 位主口 ----
            if (m_arvalid && m_arready) begin
                bus_addr   <= m_araddr;
                bus_left   <= m_arlen;
                bus_active <= 1'b1;
            end

            if (bus_active && !hit && !lin_pend) begin
                lin_addr_q <= {want_tag, 6'b0};
                lin_req_t  <= ~lin_req_t;
                lin_pend   <= 1'b1;
            end

            // 看门狗：一行数据等太久就重发请求（防跨域丢事件导致死锁）
            if (lin_pend) begin
                if (pend_wd != 10'h3FF) begin
                    pend_wd <= pend_wd + 10'd1;
                end else begin
                    pend_wd   <= 10'd0;
                    lin_req_t <= ~lin_req_t;
                end
            end else begin
                pend_wd <= 10'd0;
            end

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

    //=========================================================================
    // 5. 平台 512 位读（clk 域）
    //=========================================================================
    reg         plat_arvalid_q;
    reg  [31:0] plat_araddr_q;
    reg         req_pend;       // 有 1 个待发的行读请求（请求队列深度 1，避免丢请求）
    reg         ret_busy;       // 本次事务已收到数据，等下一次 ar 握手才允许再收

    // ---- 调试计数器（平台口字节地址 0x90 AR 次数 / 0x94 返回拍数 / 0x98 看门狗触发）----
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            dbg_ar <= 32'd0; dbg_rv <= 32'd0; dbg_wd <= 32'd0;
        end else begin
            if (plat_arvalid_q && itf_arready) dbg_ar <= dbg_ar + 32'd1;
            if (itf_rvalid)                    dbg_rv <= dbg_rv + 32'd1;
            if (pend_wd == 10'h3FF)            dbg_wd <= dbg_wd + 32'd1;
        end
    end
    assign dbg_stat = {bus_addr[15:0], 8'd0, pend_wd[5:0], 1'b0,
                       line_valid, req_pend, ret_busy, plat_arvalid_q};
    assign itf_araddr  = plat_araddr_q;
    assign itf_arvalid = plat_arvalid_q;
    assign itf_rready  = 1'b1;
    assign itf_awaddr  = 32'd0;
    assign itf_awdata  = 512'd0;
    assign itf_awvalid = 1'b0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            plat_arvalid_q <= 1'b0;
            plat_araddr_q  <= 32'd0;
            lin_data_c     <= 512'd0;
            lin_rdy_t      <= 1'b0;
            req_pend       <= 1'b0;
            ret_busy       <= 1'b0;
        end else begin
            // 请求队列（深度 1）：核心来的行请求先记住，ar 空闲再发，绝不丢
            if (lin_req_ev) req_pend <= 1'b1;

            if (plat_arvalid_q && itf_arready) begin
                plat_arvalid_q <= 1'b0;
                ret_busy       <= 1'b0;      // 新事务开始，允许收本次数据
            end

            if (req_pend && !plat_arvalid_q) begin
                plat_araddr_q  <= lin_addr_q;
                plat_arvalid_q <= 1'b1;
                req_pend       <= 1'b0;
            end

            // 数据返回：每笔事务只翻转一次（ret_busy 挡住多拍 rvalid），
            // 否则 lin_rdy_t 在 200 MHz 连翻两次，50 MHz 核看不到边沿 → 卡死
            if (itf_rvalid && !ret_busy) begin
                lin_data_c <= itf_rdata;
                lin_rdy_t  <= ~lin_rdy_t;
                ret_busy   <= 1'b1;
            end
        end
    end

    //=========================================================================
    // 6. 检测器本体（core_clk 50 MHz）
    //=========================================================================
    wire [3:0] led_i;

    ip2_axi_top #(
        .W        (W),
        .H        (H),
        .SE       (SE),
        .MAX_CAND (MAX_CAND)
    ) u_ip2 (
        .clk           (core_clk),
        .rst_n         (core_rst_n),
        .led           (led_i),

        .s_axi_awaddr  (aw_addr_c),
        .s_axi_awvalid (axi_awvalid_r),
        .s_axi_awready (axi_awready),
        .s_axi_wdata   (aw_data_c),
        .s_axi_wstrb   (4'hF),
        .s_axi_wvalid  (axi_wvalid_r),
        .s_axi_wready  (axi_wready),
        .s_axi_bresp   (axi_bresp),
        .s_axi_bvalid  (axi_bvalid),
        .s_axi_bready  (axi_bready_r),

        .s_axi_araddr  (ar_addr_c),
        .s_axi_arvalid (axi_arvalid_r),
        .s_axi_arready (axi_arready),
        .s_axi_rdata   (axi_rdata),
        .s_axi_rresp   (axi_rresp),
        .s_axi_rvalid  (axi_rvalid),
        .s_axi_rready  (axi_rready_r),

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

    assign led = led_i[1:0];

    //=========================================================================
    // 6. 片上逻辑分析仪（OnChip LA）—— 一次编译看全部
    //
    //    设计意图（吸取教训）：不要再“报错了再加一个计数器、再编译 40 分钟”。
    //    这里一次性把数据通路的关键事件全记下来（256 条环形缓冲）：
    //      1 = 平台 AR 握手（记地址）
    //      2 = 平台 R 返回（记 ret_busy/lin_rdy_t）
    //      3 = 核发出行请求（记 pend_wd/req_pend/ret_busy/arvalid）
    //      4 = 核收到行数据（同上）
    //      5 = 看门狗超时（**触发冻结**，保留崩溃瞬间的前后现场）
    //
    //    读口（平台字节地址）：
    //      0xA0 写索引（0..255）→ 读 0xA0 得到该条
    //      0xA8 读状态 {frozen, trig[3:0], 3'd0, wp[7:0]}
    //      0xAC 写 1 == 清空
    //    验证完成后把 LA_ON 置 0，这些逻辑会被综合掉，不占资源。
    //=========================================================================
    localparam LA_ON = 1'b1;

    reg  [31:0] la_mem [0:255];
    reg  [7:0]  la_wp;
    reg         la_frz;
    reg  [3:0]  la_trig;
    reg  [2:0]  s_clr;

    always @(posedge clk or negedge rst_n)
        if (!rst_n) s_clr <= 3'd0; else s_clr <= {s_clr[1:0], la_clr_t};
    wire la_clr_ev = s_clr[2] ^ s_clr[1];

    wire ev_ar = plat_arvalid_q && itf_arready;
    wire ev_r  = itf_rvalid;
    wire ev_wd = (pend_wd == 10'h3FF);

    generate if (LA_ON) begin : g_la
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                la_wp <= 8'd0; la_frz <= 1'b0; la_trig <= 4'd0;
            end else if (la_clr_ev) begin
                la_wp <= 8'd0; la_frz <= 1'b0; la_trig <= 4'd0;
            end else if (!la_frz) begin
                if (ev_ar) begin
                    la_mem[la_wp[5:0]] <= {4'h1, 4'h0, plat_araddr_q[23:0]};
                    la_wp <= la_wp + 8'd1;
                end else if (ev_r) begin
                    la_mem[la_wp[5:0]] <= {4'h2, 4'h0, ret_busy, lin_rdy_t, 22'd0};
                    la_wp <= la_wp + 8'd1;
                end else if (lin_req_ev) begin
                    la_mem[la_wp[5:0]] <= {4'h3, {2'b00, pend_wd}, req_pend, ret_busy, plat_arvalid_q, 8'd0};
                    la_wp <= la_wp + 8'd1;
                end else if (lin_rdy_ev) begin
                    la_mem[la_wp[5:0]] <= {4'h4, 12'd0, req_pend, ret_busy, plat_arvalid_q, 12'd0};
                    la_wp <= la_wp + 8'd1;
                end else if (ev_wd) begin
                    la_mem[la_wp[5:0]] <= {4'h5, 28'd0};
                    la_wp   <= la_wp + 8'd1;
                    la_frz  <= 1'b1;
                    la_trig <= 4'h1;
                end
            end
        end
        assign la_rdata  = la_mem[la_raddr];
        assign la_status = {la_frz, la_trig, 3'd0, la_wp};
    end else begin : g_la_off
        assign la_rdata  = 32'd0;
        assign la_status = 32'd0;
    end endgenerate

endmodule
