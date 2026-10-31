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
    reg  [31:0] dbg_ar, dbg_rv, dbg_wd;   // 平台口调试计数器（在 clk 域自增，见第 5 节）
    wire [31:0] dbg_stat;                 // 平台口状态快照（见第 5 节）
// --- 像素捕获：记录前 256 个"检测器看到的"像素字节（诊断用） ---
reg  [7:0]  cap_mem [0:255];
reg  [8:0]  cap_wd;
reg  [7:0]  cap_idx;
reg  [7:0]  cap_dat_q;                 // 读地址（ra 域）
    wire [5:0] ra_word = done_sel_w ? 6'h0C : itf_ra_awaddr[5:0];
    wire [5:0] rd_word = done_sel_r ? 6'h0C : itf_ra_araddr[5:0];

    reg        wr_busy, rd_busy;
    reg [31:0] rd_data_q;
    reg        rvalid_r;
    reg [11:0] rd_addr12_q;      // 读地址快照（用于调试窗口选择）
    reg [11:0] rd_tmo;           // 读超时计数（防 PS 被挂死）

    // 官方 reg_ctrl 语义：写口永远接（awready=1），绝不因为内部忙而拒绝事务，
    // 否则平台那条 AXI-Lite 写永远等不到完成，PS 会卡死在总线上。
    assign itf_ra_awready = 1'b1;
    // 读口：未在返回、且没有正在等核回应时才接。
    // 注意：arready=0 是标准 AXI 反压，PS 会等；只有"永远不回应"才会挂死，
    // 而 rd_tmo 已经保证了最多 4095 拍必回（0xDEADBEEF），所以这里拒绝是安全的。
    assign itf_ra_arready = ~rvalid_r & ~rd_busy;
    assign itf_ra_rvalid  = rvalid_r;
    wire [31:0] dbg_word = (rd_addr12_q[3:2] == 2'd0) ? dbg_ar :
                           (rd_addr12_q[3:2] == 2'd1) ? dbg_rv :
                           (rd_addr12_q[3:2] == 2'd2) ? dbg_wd : dbg_stat;
    wire        dbg_sel_q = (rd_addr12_q[11:4] == 8'h09);
    wire        cap_sel_q = (rd_addr12_q[11:0] == 12'h0B8);
    assign itf_ra_rdata   = rd_is_done_q ? {31'b0, rd_data_q[1]} :
                            cap_sel_q    ? {24'd0, cap_dat_q} :
                            dbg_sel_q    ? dbg_word :
                            rd_data_q;

    reg        wr_pend_v;        // 1 深待发槽：忙时收到的写先存着
    reg [ 5:0] wr_pend_addr;
    reg [31:0] wr_pend_data;
    reg [11:0] wr_tmo;           // 写超时计数（防核死掉后 PS 写被挂住）

    always @(posedge ra_clk or negedge ra_rst_n) begin
        if (!ra_rst_n) begin
            wr_t <= 1'b0; wr_addr_q <= 6'd0; wr_data_q <= 32'd0; wr_busy <= 1'b0;
            wr_pend_v <= 1'b0; wr_pend_addr <= 6'd0; wr_pend_data <= 32'd0;
            wr_tmo <= 12'd0;
        end else begin
            if (wr_ack_ev) begin
                wr_busy <= 1'b0;
                wr_tmo  <= 12'd0;
            end else if (wr_busy) begin
                if (wr_tmo != 12'hFFF) wr_tmo <= wr_tmo + 12'd1;
                else begin                 // 核 82us 没回应：强制解锁，PS 不再被挂
                    wr_busy <= 1'b0;
                    wr_tmo  <= 12'd0;
                end
            end
            // 新来的写：不忙 -> 直接发；忙 -> 存进待发槽（覆盖最老的）
            if (itf_ra_awvalid) begin
                if (!wr_busy && !wr_pend_v) begin
                    wr_addr_q <= ra_word;
                    wr_data_q <= itf_ra_awdata;
                    wr_t      <= ~wr_t;
                    wr_busy   <= 1'b1;
                end else begin
                    wr_pend_v    <= 1'b1;
                    wr_pend_addr <= ra_word;
                    wr_pend_data <= itf_ra_awdata;
                end
            end else if (wr_pend_v && !wr_busy) begin
                // 忙完了，把待发槽里的补发出去
                wr_addr_q  <= wr_pend_addr;
                wr_data_q  <= wr_pend_data;
                wr_t       <= ~wr_t;
                wr_busy    <= 1'b1;
                wr_pend_v  <= 1'b0;
            end
        end
    end

    //-------------------------------------------------------------------------
    // 3b. 逻辑分析仪写口（ra_clk 域）：0xA0 写索引 / 0xAC 清空
    //-------------------------------------------------------------------------
    reg la_clr_t;
    reg [7:0] la_raddr;   // 逻辑分析仪索引（本轮已移除 LA，仅保留写口不报错）
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
                // 像素捕获索引：0xB4 写要看的字节下标
                if (itf_ra_awaddr[11:0] == 12'h0B4)
                    cap_idx <= itf_ra_awdata[7:0];
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
                // 像素捕获读口：0xB8 返回 cap_mem[cap_idx]
                if (itf_ra_araddr[11:0] == 12'h0B8)
                    cap_dat_q <= cap_mem[cap_idx];
                rd_t         <= ~rd_t;
                rd_busy      <= 1'b1;
                rd_tmo       <= 12'd0;
            end
        end
    end

    //=========================================================================
    // 3.5 寄存器读写中继（core_clk 域）—— 把 ra 域的请求翻译成检测器的 AXI-Lite 事务
    //=========================================================================
    reg  [5:0]  aw_addr_c;
    reg  [31:0] aw_data_c;
    reg         axi_awvalid_r, axi_wvalid_r, axi_bready_r;
    reg  [5:0]  ar_addr_c;
    reg         axi_arvalid_r, axi_rready_r;
    reg         aw_done_r, w_done_r;
    wire        axi_awready, axi_wready;
    wire [1:0]  axi_bresp;
    wire        axi_bvalid, axi_arready;
    wire [31:0] axi_rdata;
    wire [1:0]  axi_rresp;
    wire        axi_rvalid;

    always @(posedge core_clk or negedge core_rst_n) begin
        if (!core_rst_n) begin
            aw_addr_c <= 6'd0; aw_data_c <= 32'd0;
            axi_awvalid_r <= 1'b0; axi_wvalid_r <= 1'b0; axi_bready_r <= 1'b0;
            ar_addr_c <= 6'd0; axi_arvalid_r <= 1'b0; axi_rready_r <= 1'b0;
            aw_done_r <= 1'b0; w_done_r <= 1'b0;
            wr_ack_t <= 1'b0; rd_ack_t <= 1'b0; rd_data_c <= 32'd0;
        end else begin
            // ---- 写 ----
            if (wr_req_ev) begin
                aw_addr_c     <= wr_addr_q;
                aw_data_c     <= wr_data_q;
                axi_awvalid_r <= 1'b1;
                axi_wvalid_r  <= 1'b1;
            end
            if (axi_awvalid_r && axi_awready) begin axi_awvalid_r <= 1'b0; aw_done_r <= 1'b1; end
            if (axi_wvalid_r  && axi_wready ) begin axi_wvalid_r  <= 1'b0; w_done_r  <= 1'b1; end
            if (aw_done_r && w_done_r) axi_bready_r <= 1'b1;
            if (axi_bvalid && axi_bready_r) begin
                axi_bready_r <= 1'b0; aw_done_r <= 1'b0; w_done_r <= 1'b0;
                wr_ack_t <= ~wr_ack_t;
            end
            // ---- 读 ----
            if (rd_req_ev) begin
                ar_addr_c     <= rd_addr_q;
                axi_arvalid_r <= 1'b1;
                axi_rready_r  <= 1'b1;
            end
            if (axi_arvalid_r && axi_arready) axi_arvalid_r <= 1'b0;
            if (axi_rvalid && axi_rready_r) begin
                axi_rready_r <= 1'b0;
                rd_data_c <= axi_rdata;
                rd_ack_t  <= ~rd_ack_t;
            end
        end
    end

    //=========================================================================
    // 4. 行流读取（学长 dma.v 的模型）—— core_clk 域发请求、clk 域取数
    //
    //   平台数据口：一行一个 AR（地址 = 帧基址 + 64×行号），回来就是 512 位 = 64 字节
    //   = 64 个连续像素（capdump 实测证实：第 7 行首字节 = 像素 448 的值）。
    //   所以这里不模拟 64 位突发：一行取回后，按 1 字节/拍直接推进检测器的像素 FIFO。
    //=========================================================================
    localparam NPIX_C = W * H;                  // 本帧像素数
    localparam NLINE  = (NPIX_C + 63) / 64;     // 需要的行数

    reg  [31:0] frame_base;      // 帧基址（从寄存器 0x04 嗅探）
    reg  [31:0] line_idx;        // 下一个要请求的行号
    reg         feed_on;         // 正在喂帧
    reg  [3:0]  inflight;        // 已请求未取回的行数
    reg  [31:0] px_pushed;       // 已推给检测器的像素数

    // 外部像素直推口的连线（先声明，后面接实例）
    wire        i_ext_valid;
    wire [7:0]  i_ext_data;
    wire        o_ext_ready;
    wire        o_ext_go;
    // 实例化时不再使用的 AXI 主口，用哑线兜住
    wire [31:0] dum_awaddr; wire [7:0] dum_awlen; wire [2:0] dum_awsize; wire [1:0] dum_awburst;
    wire        dum_awvalid; wire [63:0] dum_wdata; wire [7:0] dum_wstrb; wire dum_wlast; wire dum_wvalid;
    wire        dum_bready; wire [31:0] dum_araddr; wire [7:0] dum_arlen; wire [2:0] dum_arsize;
    wire [1:0]  dum_arburst; wire dum_arvalid; wire dum_rready;

    reg        start_req;        // CTRL 写过 start
    reg  [511:0] lbuf;           // 当前行
    reg  [5:0]   lbcnt;          // 行内字节计数 0..63
    reg          lbusy;          // 有一行正在推

    wire [7:0] ext_byte = lbuf[{lbcnt, 3'b000} +: 8];
    wire       ext_space = o_ext_ready;

    assign i_ext_valid = lbusy;
    assign i_ext_data  = ext_byte;

    always @(posedge core_clk or negedge core_rst_n) begin
        if (!core_rst_n) begin
            frame_base <= 32'h3010_0000;
            feed_on    <= 1'b0;
            line_idx   <= 32'd0;
            inflight   <= 4'd0;
            px_pushed  <= 32'd0;
            lbusy      <= 1'b0;
            lbcnt      <= 6'd0;
            start_req  <= 1'b0;
        end else begin
            // ---- 嗅探寄存器写：0x00 CTRL(bit0=start)、0x04 FRAME_ADDR ----
            if (wr_req_ev) begin
                if (wr_addr_q == 6'h04) frame_base <= wr_data_q;
                if (wr_addr_q == 6'h00 && wr_data_q[0]) begin
                    // 只记下"想启动"；真正开始推流等检测器 FSM 的 o_ext_go
                    start_req <= 1'b1;
                end
            end

            // ---- 检测器开始取数的脉冲（F_RST 末拍）→ 正式开喂 ----
            if (o_ext_go && start_req) begin
                start_req <= 1'b0;
                feed_on   <= 1'b1;
                line_idx  <= 32'd0;
                inflight  <= 4'd0;
                px_pushed <= 32'd0;
                lbusy     <= 1'b0;
                lbcnt     <= 6'd0;
            end

            // ---- 发新行请求：在途 < 6 且还有像素没推完 ----
            if (feed_on && !lbusy && (inflight < 4'd1) &&
                (px_pushed + ({1'b0, inflight} << 6) < NPIX_C)) begin
                lin_addr_q <= frame_base + (line_idx << 6);
                lin_req_t  <= ~lin_req_t;
                line_idx   <= line_idx + 32'd1;
                inflight   <= inflight + 4'd1;
            end

            // ---- 收行数据 ----
            if (lin_rdy_ev) begin
                lbuf  <= lin_data_c;
                lbcnt <= 6'd0;
                lbusy <= 1'b1;
            end

            // ---- 推像素：1 字节/拍 ----
            if (lbusy && ext_space) begin
                px_pushed <= px_pushed + 32'd1;
                if (lbcnt == 6'd63) begin
                    lbcnt  <= 6'd0;
                    lbusy  <= 1'b0;
                    if (inflight != 4'd0) inflight <= inflight - 4'd1;
                end else begin
                    lbcnt <= lbcnt + 6'd1;
                end
            end

            if (px_pushed >= NPIX_C) feed_on <= 1'b0;
        end
    end

    //=========================================================================
    // 5. 平台 512 位读（clk 域）：一行一个 AR
    //=========================================================================
    reg         plat_arvalid_q;
    reg  [31:0] plat_araddr_q;
    reg         req_pend;
    reg         ret_busy;
    reg  [9:0]  pend_wd;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            dbg_ar <= 32'd0; dbg_rv <= 32'd0; dbg_wd <= 32'd0;
        end else begin
            if (plat_arvalid_q && itf_arready) dbg_ar <= dbg_ar + 32'd1;
            if (itf_rvalid)                    dbg_rv <= dbg_rv + 32'd1;
            if (pend_wd == 10'h3FF)            dbg_wd <= dbg_wd + 32'd1;
        end
    end
    assign dbg_stat = {px_pushed[15:0], line_idx[7:0], pend_wd[5:0], 1'b0,
                       lbusy, req_pend, ret_busy, plat_arvalid_q};

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
            pend_wd        <= 10'd0;
        end else begin
            if (lin_req_ev) begin
                req_pend      <= 1'b1;
                plat_araddr_q <= lin_addr_q;
            end

            if (req_pend && !plat_arvalid_q && !ret_busy)
                plat_arvalid_q <= 1'b1;

            if (plat_arvalid_q && itf_arready) begin
                plat_arvalid_q <= 1'b0;
                req_pend       <= 1'b0;
                ret_busy       <= 1'b1;
                pend_wd        <= 10'd0;
            end

            if (itf_rvalid) begin
                lin_data_c <= itf_rdata;
                lin_rdy_t  <= ~lin_rdy_t;
                ret_busy   <= 1'b0;
            end

            if (plat_arvalid_q) begin
                if (pend_wd != 10'h3FF) pend_wd <= pend_wd + 10'd1;
                else begin
                    pend_wd        <= 10'd0;
                    req_pend       <= 1'b1;
                    plat_arvalid_q <= 1'b0;
                end
            end
        end
    end

    //=========================================================================
    // 6. 像素捕获（诊断）：记录前 256 个真正送进检测器的字节
    //=========================================================================
    always @(posedge core_clk or negedge core_rst_n)
        if (!core_rst_n) cap_wd <= 9'd0;
        else if (lbusy && ext_space && (cap_wd != 9'h1FF)) cap_wd <= cap_wd + 9'd1;

    always @(posedge core_clk)
        if (lbusy && ext_space && (cap_wd < 9'd256)) cap_mem[cap_wd[7:0]] <= ext_byte;

    //=========================================================================
    // 7. 检测器本体（core_clk 50 MHz，像素由外部直推 USE_EXT=1）
    //=========================================================================
    wire [3:0] led_i;

    ip2_axi_top #(
        .W        (W),
        .H        (H),
        .SE       (SE),
        .MAX_CAND (MAX_CAND),
        .USE_EXT  (1)
    ) u_ip2 (
        .clk           (core_clk),
        .rst_n         (core_rst_n),
        .led           (led_i),

        .i_ext_data    (i_ext_data),
        .i_ext_valid   (i_ext_valid),
        .o_ext_ready   (o_ext_ready),
        .o_ext_go      (o_ext_go),

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

        .m_axi_araddr  (dum_araddr),
        .m_axi_arlen   (dum_arlen),
        .m_axi_arsize  (dum_arsize),
        .m_axi_arburst (dum_arburst),
        .m_axi_arvalid (dum_arvalid),
        .m_axi_arready (1'b0),
        .m_axi_rdata   (64'd0),
        .m_axi_rresp   (2'b00),
        .m_axi_rlast   (1'b0),
        .m_axi_rvalid  (1'b0),
        .m_axi_rready  (dum_rready),

        .m_axi_awaddr  (dum_awaddr),
        .m_axi_awlen   (dum_awlen),
        .m_axi_awsize  (dum_awsize),
        .m_axi_awburst (dum_awburst),
        .m_axi_awvalid (dum_awvalid),
        .m_axi_awready (1'b0),
        .m_axi_wdata   (dum_wdata),
        .m_axi_wstrb   (dum_wstrb),
        .m_axi_wlast   (dum_wlast),
        .m_axi_wvalid  (dum_wvalid),
        .m_axi_wready  (1'b0),
        .m_axi_bresp   (2'b00),
        .m_axi_bvalid  (1'b0),
        .m_axi_bready  (dum_bready)
    );

    assign led = led_i[1:0];

endmodule
