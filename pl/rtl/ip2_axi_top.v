// ip2_axi_top.v —— IP2 加速器顶层（AXI4-Lite 控制 + AXI4 主口搬数据）
//
// 整条链路：
//   PS 写 AXI-Lite 寄存器（帧地址 + start）
//     -> ip2_axi_master_rd  从 DDR 读 230,400 B 灰度帧 -> 像素流
//     -> ip2_top_stream     Top-Hat 5x5 -> CFAR 31x31(真实 std) -> CCL 单趟
//     -> 收 36 B 候选表
//     -> ip2_axi_master_wr  写回 DDR（+0x00 候选表 / +0x40 状态字）
//     -> STATUS 寄存器 done=1，PS 轮询取结果
//
// 关键点（踩过的坑，别改）：
//   1. IP2 的 CFAR / CCL 是「一帧一次」状态机，跑完停在 S_DONE 不回 S_RUN
//      => 帧间必须整链复位（F_FEED / F_WAIT 之外 chain_rst_n 保持 0）。
//   2. CFAR 在虚拟光栅的 PAD 列会拉低 i_ready（每行 30 拍），
//      => 读主机的 o_ready 必须接 chain_i_ready，反压一路回传到 AXI 读口。
//   3. CCL 在 S_DONE 里 o_valid 一直保持高 => 只收前 36 字节，别用 valid 当结束。
//
// 寄存器映射（AXI4-Lite，32 bit，字节地址）：
//   0x00 CTRL         W  bit0 = start（写 1 启动一帧，自清）
//   0x04 FRAME_ADDR   W  输入帧物理地址（默认 0x30100000）
//   0x08 RESULT_ADDR  W  输出区物理地址（默认 0x31000000）
//   0x0C STATUS       R  bit0 busy / bit1 done / bit2 error /
//                        [15:8] n_cand / [23:16] 已完成帧计数
//   0x10 CAND_WIN     W  候选表窗口索引（0..112）；R 读该字
//   0x14 VERSION      R  0x0001_0000
//   0x18~0x38 LEGACY  R  兼容视图：9 个字 = 36 字节（旧 5 候选格式）
//   0x3C ST_MIRROR    R  {bit31 done, bit30 err, [15:0] frame_id}
module ip2_axi_top #(
    parameter W = 640,
    parameter H = 360,
    parameter MAX_CAND = 64,
    parameter SE = 21,          // Top-Hat 结构元边长（奇数）：21 可检 ≤20 px 目标
    parameter K = 0,            // CFAR 系数：判决 x > mean + K*sd + FLOOR
    parameter FLOOR = 2,        // CFAR 底噪
    parameter MODE = 0,         // 0=Top-Hat(亮目标) 1=Black-Hat(暗目标)
    parameter DENOISE = 1,      // CCL 去孤立点（板级打开，抑制候选表抖动）
    parameter USE_EXT  = 0,     // 1=像素由外部直推（三域平台行流模式），0=AXI 主口（独立版）
    parameter [31:0] DEF_FRAME_ADDR  = 32'h3010_0000,
    parameter [31:0] DEF_RESULT_ADDR = 32'h3100_0000
)(
    input  wire        clk,
    input  wire        rst_n,
    output wire [3:0]  led,

    // ---------------- 外部像素直推口（USE_EXT=1 时有效，仿学长 dma.v 的行流模型）----
    input  wire [7:0]  i_ext_data,
    input  wire        i_ext_valid,
    output wire        o_ext_ready,
    output wire        o_ext_go,        // 一行流模式：一帧开始取数的脉冲

    // ---------------- AXI4-Lite 从口（PS 控制） ----------------
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
    output reg  [31:0] s_axi_rdata,
    output wire [1:0]  s_axi_rresp,
    output reg         s_axi_rvalid,
    input  wire        s_axi_rready,

    // ---------------- AXI4 主口：读帧 ----------------
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

    // ---------------- AXI4 主口：写结果 ----------------
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
    localparam NPIX = W * H;
    localparam [31:0] NPIX_V = NPIX;
    // 冲刷拍数：整帧喂完后必须继续往链路里塞"假像素"，把流水线里剩下的有效像素顶出来，
    // 否则 CCL 永远数不到第 N 个 valid，也就不会进 S_MERGE/S_OUT（实测：卡在 218212/230400）。
    // 需要的拍数 = 链路总延迟 = TopHat 延迟 + CFAR 中心偏移。
    //   TopHat: TD = 2*((SE/2)*W + SE/2 + 1) + 1     （SE=21,W=640 → 12823）
    //   CFAR  : CENTER_OFF = 15*(W+15) + 15          （W=640 → 9840）
    // SE 从 5 放大到 21 后延迟从 ~12632 涨到 ~22668，旧的 15353 会不够，这里按公式算。
    localparam TD_T   = 2 * (((SE/2)*W) + (SE/2) + 1) + 1;
    localparam CF_OFF = 15 * (W + 15) + 15;
    localparam DRAIN  = TD_T + CF_OFF + 2048;

    // ------------------------------------------------------------------
    // AXI4-Lite 寄存器
    // ------------------------------------------------------------------
    reg  [31:0] frame_addr;
    reg  [31:0] result_addr;
    reg  [15:0] frame_id;
    reg         start_r;        // 单拍启动脉冲
    reg         done_flag;
    reg         err_flag;
    reg  [7:0]  n_cand_r;
    reg  [6:0]  cand_rd_idx;   // 候选表窗口索引（0x40 写）
    reg [31:0] legacy_ram [0:8];         // 兼容视图：前 9 字（36 字节）常驻寄存器
    wire [31:0] cand_rdata;     // 候选表窗口数据（0x1C 读）
    reg  [7:0]  frm_cnt;

    wire        busy_w;         // 声明提前：AXI-Lite 读 STATUS 时要用

    reg         aw_got, w_got, bvalid_r;
    reg  [5:0]  awaddr_l;
    reg  [31:0] wdata_l;
    reg  [3:0]  wstrb_l;

    assign s_axi_awready = !aw_got && !bvalid_r;
    assign s_axi_wready  = !w_got  && !bvalid_r;
    assign s_axi_bvalid  = bvalid_r;
    assign s_axi_bresp   = 2'b00;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            frame_addr  <= DEF_FRAME_ADDR;
            result_addr <= DEF_RESULT_ADDR;
            frame_id    <= 16'd0;
            start_r     <= 1'b0;
            // 注意：done_flag / err_flag / n_cand_r / frm_cnt 的驱动
            // 统一放在下面的帧状态机块里，本块不再复位它们。
            // （原先两处都复位 → Vivado 报 CRITICAL WARNING [Synth 8-3352]
            //   multi-driven net，n_cand_r 的位还被当成常量 GND，STATUS
            //   里读出来的候选数可能是 0。）
            aw_got      <= 1'b0;
            w_got       <= 1'b0;
            bvalid_r    <= 1'b0;
            awaddr_l    <= 6'd0;
            wdata_l     <= 32'd0;
            wstrb_l     <= 4'd0;
        end else begin
            // start 自清（1 拍脉冲）
            if (start_r) start_r <= 1'b0;

            // ---- 写通道 ----
            if (s_axi_awvalid && s_axi_awready) begin
                awaddr_l <= s_axi_awaddr;
                aw_got   <= 1'b1;
            end
            if (s_axi_wvalid && s_axi_wready) begin
                wdata_l <= s_axi_wdata;
                wstrb_l <= s_axi_wstrb;
                w_got   <= 1'b1;
            end
            if (aw_got && w_got) begin
                case (awaddr_l[5:0])
                    6'h00: if (wstrb_l[0]) start_r <= wdata_l[0];
                    6'h04: frame_addr  <= wdata_l;
                    6'h08: result_addr <= wdata_l;
                    6'h10: cand_rd_idx <= wdata_l[6:0];   // 候选表窗口索引（写 0x10，读 0x10 取该字）
                    default: ;   // 0x0C/0x14 只读
                endcase
                aw_got   <= 1'b0;
                w_got    <= 1'b0;
                bvalid_r <= 1'b1;
            end
            if (bvalid_r && s_axi_bready) bvalid_r <= 1'b0;
        end
    end

    // ---- 读通道 ----
    reg        r_pend;
    reg  [7:0] araddr_l;
    assign s_axi_arready = !r_pend && !s_axi_rvalid;
    assign s_axi_rresp   = 2'b00;

    // ---- 调试探针（wire 先声明，赋值统一放文件末尾，满足“先声明后使用”）----
    wire [31:0] dbg_pcount;
    wire [31:0] dbg_stat1;
    wire [31:0] dbg_ccl;
    wire [31:0] dbg_hand;
    wire [31:0] ch_dbg_vcnt;    // CCL 内部 valid 计数（0x34）
    wire [31:0] dbg_thv;      // TopHat→CFAR 的 valid 计数
    wire [31:0] dbg_cfv;      // CFAR→CCL 的 valid 计数
    wire [31:0] dbg_rdy;      // {cf_ready 计数低 16 位, ch_ready 计数低 16 位}
    // 候选表窗口读：PS 先写索引（0x18），再读数据（0x1C），113 次读完 452 字节
    wire [31:0] st_mirror, fsm_snap;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            r_pend     <= 1'b0;
            araddr_l   <= 6'd0;
            s_axi_rvalid <= 1'b0;
            s_axi_rdata  <= 32'd0;
        end else begin
            if (s_axi_arvalid && s_axi_arready) begin
                araddr_l <= s_axi_araddr;
                r_pend   <= 1'b1;
            end else if (r_pend) begin
                r_pend       <= 1'b0;
                s_axi_rvalid <= 1'b1;
                case (araddr_l[5:0])
                    6'h00:   s_axi_rdata <= {31'd0, start_r};
                    6'h04:   s_axi_rdata <= frame_addr;
                    6'h08:   s_axi_rdata <= result_addr;
                    6'h0C:   s_axi_rdata <= {8'h00, frm_cnt, n_cand_r, 5'd0,
                                             err_flag, done_flag, busy_w};
                    6'h10:   s_axi_rdata <= cand_rdata;      // 64 候选窗口数据（写 0x10 选字）
                    6'h14:   s_axi_rdata <= 32'h0001_0000;
                    // ---- 候选表兼容镜像（S 的 web_console 读 0x18~0x3C 共 9 字 = 36 字节）----
                    6'h18:   s_axi_rdata <= legacy_ram[0];   // byte0 = n_cand
                    6'h1C:   s_axi_rdata <= legacy_ram[1];
                    6'h20:   s_axi_rdata <= legacy_ram[2];
                    6'h24:   s_axi_rdata <= legacy_ram[3];
                    6'h28:   s_axi_rdata <= legacy_ram[4];
                    6'h2C:   s_axi_rdata <= legacy_ram[5];
                    6'h30:   s_axi_rdata <= legacy_ram[6];
                    6'h34:   s_axi_rdata <= legacy_ram[7];
                    6'h38:   s_axi_rdata <= legacy_ram[8];
                    6'h3C:   s_axi_rdata <= st_mirror;     // {done,err,14'd0,frame_id}
                    // ---- 64 候选窗口（写 0x10 选字，读 0x10 取该字，共 113 字 = 452 字节）----
                    default: s_axi_rdata <= 32'h0;
                endcase
            end
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
        end
    end

    // ------------------------------------------------------------------
    // 主状态机
    // ------------------------------------------------------------------
    localparam F_IDLE = 3'd0,   // 等 start
               F_RST  = 3'd1,   // 整链复位 32 拍
               F_FILL = 3'd2,   // 读主机把整帧搬进片内帧缓冲（链保持复位）
               F_FEED = 3'd3,   // 链路连续吃掉整帧（无空拍）
               F_WAIT = 3'd4,   // 等 CCL 吐完 36 字节
               F_WRITE= 3'd5,   // AXI 写回
               F_FIN  = 3'd6;

    localparam AW_F = 18;       // 帧缓冲深度 2^18 = 262144 ≥ 230400

    reg [2:0]  fst;
    // 候选表缓冲：1 + MAX_CAND*7 字节，向上补齐到 4 的倍数（449 -> 452）
    localparam N_CAND_BYTES = 1 + MAX_CAND*7;
    localparam N_BYTES      = ((N_CAND_BYTES + 3) / 4) * 4;
    localparam N_WORDS      = N_BYTES / 4;
    reg [8:0]  ocount;          // 已收候选表字节数（0..N_BYTES-1）
    reg [31:0] cand_w;          // 正在拼装的 32 位字（按字节槽位写）
    reg [31:0] cand_ram [0:N_WORDS-1];   // 1 写 1 读 -> LUTRAM
    reg [31:0] pcount;          // 已喂像素数
    reg [4:0]  rstc;
    reg [31:0] wdog;

    assign busy_w = (fst != F_IDLE);
    // 链复位：只在 F_FEED / F_WAIT 期间放开
    wire chain_rst_n = rst_n && (fst == F_FEED || fst == F_WAIT);

    // ---- 读主机 ----
    wire        rd_start;
    wire        rd_busy, rd_done, rd_error;
    wire [7:0]  rd_data;
    wire        rd_valid, rd_ready;

    // ---- 写主机 ----
    wire        wr_start;
    wire        wr_busy, wr_done, wr_error;

    // ---- IP2 链 ----
    wire [7:0]  ch_o_data;
    wire        ch_o_valid;
    wire        ch_i_ready;
    wire [2:0]  ch_dbg_state;
    wire [17:0] ch_dbg_px;
    wire        cha_thv, cha_cfv, cha_cfrdy, cha_chrdy;   // 链内部探针
    reg  [7:0]  err_code;       // 出错现场编码（见 F_FIN 前的各超时分支）

    // ---- 帧缓冲（RD 主机 → IP2 链）----
    // 必需：IP2 是连续像素流假设，AXI 读主机在 burst 边界/反压恢复处会有
    // 几拍 valid 空隙，直接用会让 5×5/31×31 窗口几何错位
    // （实测：像素 9216/9216 全对，候选表却错 3~8 字节）。
    // 深度取 2^18 = 262144 ≥ 640×360，先整帧装满再让链路连续吃。
    wire [7:0]   fifo_data;
    wire         fifo_valid;
    wire         fifo_full;
    wire [AW_F:0] fifo_level;
    // 只有 F_FEED 才允许链路从帧缓冲取数；F_FILL 期间链路在复位，
    // 若让它出队会把缓冲提前抽干（frame_loaded 永远不满足 → 卡死）。
    // F_FEED 分两段：
    //   ①feed_real —— 从帧缓冲取真实像素（pcount 计数）；
    //   ②feed_pad  —— 真实像素喂完后，继续灌 0 拍把 CFAR 流水线里剩下的有效像素顶出来。
    // 只有 feed_real 才出队帧缓冲；feed_pad 期间 fifo 停下，避免把缓冲抽干。
    reg  [17:0]  drain_cnt;     // 已灌入的冲刷假像素数

    wire         feed_real = (fst == F_FEED) && (pcount < NPIX_V);
    wire         feed_pad  = (fst == F_FEED) && (pcount >= NPIX_V) &&
                             (drain_cnt < DRAIN[17:0]);
    wire         chain_en  = (fst == F_FEED);
    wire         fifo_pop  = fifo_valid && ch_i_ready && feed_real;

    always @(posedge clk) begin
        if (!rst_n)                drain_cnt <= 18'd0;
        else if (!chain_rst_n)     drain_cnt <= 18'd0;
        else if (feed_pad && ch_i_ready) drain_cnt <= drain_cnt + 18'd1;
    end

    assign rd_ready = !fifo_full;                       // 只受帧缓冲满反压

    // 帧缓冲清空：只在 F_RST 的前 16 拍（此时读主机还没发出 AR，
    // 清掉上一帧残留的 120 字节，避免整帧像素流平移）。
    wire fifo_clr = (fst == F_RST) && (rstc < 5'd16);

    wire       ext_mode      = (USE_EXT != 0);
    // ext 模式下：F_RST 期间 FIFO 会被清空，所以这段时间的写入要丢掉；
    // 真正的推流从 rd_start（F_RST 末拍）之后才算数。
    wire       ext_wr_ok     = (fst != F_RST);
    wire       fifo_wr_en    = ext_mode ? (i_ext_valid && ext_wr_ok) : rd_valid;
    wire [7:0] fifo_wr_data  = ext_mode ? i_ext_data  : rd_data;
    assign     o_ext_ready   = ~fifo_full;
    assign     o_ext_go      = rd_start;

    ip2_pix_fifo #(.DEPTH(262144), .AW(AW_F)) u_pixfifo (
        .clk(clk), .rst_n(rst_n), .clr(fifo_clr),
        .wr_en(fifo_wr_en), .wr_data(fifo_wr_data), .wr_full(fifo_full),
        .rd_data(fifo_data), .rd_valid(fifo_valid), .rd_ready(ch_i_ready && feed_real),
        .level(fifo_level)
    );

    generate if (USE_EXT == 0) begin : g_rd_master
    ip2_axi_master_rd #(.FIFO_AW(6), .BURST(32)) u_rd (
        .clk(clk), .rst_n(rst_n),
        .start(rd_start),
        .base_addr(frame_addr),
        // 多读 512 字节：帧缓冲已按每帧清空，但读主机按 256 字节突发取数，
        // 多读 2 个突发保证整帧 NPIX 个像素全部到位（多余部分下一帧被 clr 丢掉）。
        .n_bytes(NPIX_V + 32'd512 + (32*W)),
        .busy(rd_busy), .done(rd_done), .error(rd_error),
        .o_data(rd_data), .o_valid(rd_valid), .o_ready(rd_ready),
        .m_araddr(m_axi_araddr), .m_arlen(m_axi_arlen),
        .m_arsize(m_axi_arsize), .m_arburst(m_axi_arburst),
        .m_arvalid(m_axi_arvalid), .m_arready(m_axi_arready),
        .m_rdata(m_axi_rdata), .m_rresp(m_axi_rresp), .m_rlast(m_axi_rlast),
        .m_rvalid(m_axi_rvalid), .m_rready(m_axi_rready)
    );
    end else begin : g_no_master
        reg [17:0] ext_cnt;
        always @(posedge clk) begin
            if (!rst_n)        ext_cnt <= 18'd0;
            else if (rd_start) ext_cnt <= 18'd0;
            else if (fifo_wr_en) ext_cnt <= ext_cnt + 18'd1;
        end
        assign rd_data  = 8'd0;
        assign rd_valid = 1'b0;
        assign rd_busy  = 1'b0;
        assign rd_done  = (ext_cnt >= NPIX_V);
        assign rd_error = 1'b0;
        assign m_axi_araddr  = 32'd0;
        assign m_axi_arlen   = 8'd0;
        assign m_axi_arsize  = 3'd0;
        assign m_axi_arburst = 2'd0;
        assign m_axi_arvalid = 1'b0;
        assign m_axi_rready  = 1'b0;
    end endgenerate

    // 非 ext 模式下 o_ext_go 也要有驱动
    wire ext_go_unused = o_ext_go;

    ip2_top_stream #(.W(W), .H(H), .MAX_CAND(MAX_CAND), .SE(SE), .MODE(MODE), .K(K), .FLOOR(FLOOR),
                     .DENOISE(DENOISE)) u_chain (
        .clk(clk), .rst_n(chain_rst_n),
        .i_data(feed_real ? fifo_data : 8'd0),
        .i_valid(feed_real ? fifo_valid : feed_pad),
        .i_ready(ch_i_ready),
        .o_data(ch_o_data), .o_valid(ch_o_valid), .o_ready(1'b1),
        .dbg_state(ch_dbg_state), .dbg_px(ch_dbg_px),
        .dbg_th_valid(cha_thv), .dbg_cf_valid(cha_cfv),
        .dbg_cf_ready(cha_cfrdy), .dbg_ch_ready(cha_chrdy),
        .dbg_ccl_vcnt(ch_dbg_vcnt)
    );

    ip2_axi_master_wr u_wr (
        .clk(clk), .rst_n(rst_n),
        .start(wr_start),
        .base_addr(result_addr),
        .cand_bytes(288'd0),          // DDR 写回已停用：候选表改走寄存器窗口（写主控保留以维持 FSM 计时）
        .status_word({1'b1, err_flag, 14'd0, frame_id}),
        .busy(wr_busy), .done(wr_done), .error(wr_error),
        .m_awaddr(m_axi_awaddr), .m_awlen(m_axi_awlen),
        .m_awsize(m_axi_awsize), .m_awburst(m_axi_awburst),
        .m_awvalid(m_axi_awvalid), .m_awready(m_axi_awready),
        .m_wdata(m_axi_wdata), .m_wstrb(m_axi_wstrb), .m_wlast(m_axi_wlast),
        .m_wvalid(m_axi_wvalid), .m_wready(m_axi_wready),
        .m_bresp(m_axi_bresp), .m_bvalid(m_axi_bvalid), .m_bready(m_axi_bready)
    );

    assign rd_start = (fst == F_RST) && (rstc == 5'd31);
    assign wr_start = (fst == F_WAIT) && (ocount >= N_BYTES[8:0]) && !wr_busy && !wr_done;

    // 帧缓冲是否已装满（读主机把 NPIX 个像素全部搬进 FIFO/帧缓存）
    wire frame_loaded = rd_done && (fifo_level >= NPIX);

    // 候选表收集：每 4 字节拼成一个 32 位字写进 cand_ram（1 写 1 读 -> 可推断 LUTRAM）
    // 注意：清缓冲只能用 F_RST，不能用 !chain_rst_n（F_WRITE/F_FIN 时它是 0，会把刚收好的表清掉）
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ocount   <= 9'd0;
        end else if (fst == F_RST) begin
            ocount   <= 9'd0;
        end else if (ch_o_valid && (ocount < N_BYTES[8:0])) begin
            ocount   <= ocount + 9'd1;
        end
    end

    // 写口独立 always 块（写进状态机 case 里 Procise 不认 RAM）
    // 按字节槽位拼 32 位字：第 0 字节 -> [7:0]，保证小端顺序正确
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cand_w <= 32'd0;
        end else if (fst == F_RST) begin
            cand_w <= 32'd0;
        end else if (ch_o_valid && (ocount < N_BYTES[8:0])) begin
            case (ocount[1:0])
                2'd0:    cand_w[7:0]   <= ch_o_data;
                2'd1:    cand_w[15:8]  <= ch_o_data;
                2'd2:    cand_w[23:16] <= ch_o_data;
                default: cand_w[31:24] <= ch_o_data;
            endcase
        end
    end

    always @(posedge clk) begin
        if (ch_o_valid && (ocount < N_BYTES[8:0]) && (ocount[1:0] == 2'd3)) begin
            cand_ram[ocount[8:2]] <= {ch_o_data, cand_w[23:0]};
            if (ocount[8:2] < 9) legacy_ram[ocount[8:2]] <= {ch_o_data, cand_w[23:0]};
        end
    end

    // 已喂像素计数：必须数「链路真正吃进」的像素（FIFO 出队），
    // 不能数读主机侧的 rd_valid —— 加了 FIFO 之后两者不再等价。
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)               pcount <= 32'd0;
        else if (!chain_rst_n)    pcount <= 32'd0;
        else if (fifo_pop)        pcount <= pcount + 32'd1;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fst      <= F_IDLE;
            rstc     <= 5'd0;
            wdog     <= 32'd0;
            done_flag<= 1'b0;
            err_flag <= 1'b0;
            n_cand_r <= 8'd0;
            frm_cnt  <= 8'd0;
        end else begin
            case (fst)
            F_IDLE: begin
                rstc     <= 5'd0;
                wdog     <= 32'd0;
                if (start_r) begin
                    done_flag <= 1'b0;
                    err_flag  <= 1'b0;
                    err_code  <= 8'd0;
                    fst       <= F_RST;
                end
            end
            F_RST: begin
                done_flag <= 1'b0;
                if (rstc == 5'd31) begin
                    fst  <= F_FILL;
                    rstc <= 5'd0;
                end else begin
                    rstc <= rstc + 5'd1;
                end
            end
            F_FILL: begin
                // 等读主机把整帧搬进片内帧缓冲（FIFO 深度 = 一帧像素数），
                // 这样链路开始吃数据后永不出现空拍 —— IP2 的 5×5/31×31
                // 窗口几何要求连续像素，一个空拍就整帧错位。
                wdog <= wdog + 32'd1;
                if (rd_error) begin
                    err_flag <= 1'b1;
                    err_code <= 8'd1;      // 读 DDR 出错（RRESP 异常）
                end
                if (frame_loaded) begin
                    fst  <= F_FEED;
                    wdog <= 32'd0;
                end else if (wdog > 32'd12_000_000) begin
                    err_flag <= 1'b1;      // 读帧超时
                    err_code <= 8'd2;
                    fst      <= F_FIN;
                end
            end
            F_FEED: begin
                // 注意：这里的读是「冲刷拍」（读满一帧后额外多读 512+32W 字节，
                // 目的只是把 CFAR/CCL 流水线里的余量顶出来），平台对这个越界区间
                // 会回非 OKAY 的 RRESP。这类错误不影响已经进 FIFO 的整帧像素，
                // 所以只在 F_FILL（真正搬帧）里把 rd_error 当致命错误。
                if (rd_error && !frame_loaded) begin
                    err_flag <= 1'b1;
                    err_code <= 8'd1;
                end
                // 断粮检测：连续 4M 拍没进展就报错（真像素与冲刷像素都算进展）
                if (fifo_pop || (feed_pad && ch_i_ready)) wdog <= 32'd0;
                else                                       wdog <= wdog + 32'd1;
                // 结束条件（三选一）：
                //   ①候选表已经吐满 36 字节 —— 正常成功（CCL 数到第 N 个 valid 后会自己在
                //     S_MERGE/S_OUT 里跑完，不需要再喂像素）；
                //   ②冲刷拍数够了 —— 交给 F_WAIT 的超时判断；
                //   ③断粮 4M 拍 —— 报错。
                if (ocount >= N_BYTES[8:0]) begin
                    fst  <= F_WAIT;
                    wdog <= 32'd0;
                end else if (drain_cnt >= DRAIN[17:0]) begin
                    fst  <= F_WAIT;
                    wdog <= 32'd0;
                end else if (wdog > 32'd4_000_000) begin
                    err_flag <= 1'b1;      // 链路吃不到像素（帧缓冲断粮）
                    err_code <= 8'd3;
                    fst      <= F_FIN;
                end
            end
            F_WAIT: begin
                wdog <= wdog + 32'd1;
                if (ocount >= N_BYTES[8:0]) begin
                    n_cand_r <= legacy_ram[0][7:0];
                    wdog     <= 32'd0;
                    fst      <= F_WRITE;
                end else if (wdog > 32'd40_000_000) begin
                    err_flag <= 1'b1;     // 超时：链路没吐完候选表（0.8 s）
                    err_code <= 8'd4;
                    fst      <= F_FIN;
                end
            end
            F_WRITE: begin
                wdog <= wdog + 32'd1;
                if (wr_done) begin
                    if (wr_error) begin
                        err_flag <= 1'b1;
                        err_code <= 8'd6;
                    end
                    done_flag <= 1'b1;
                    frm_cnt   <= frm_cnt + 8'd1;
                    fst       <= F_FIN;
                end else if (wdog > 32'd1_000_000) begin
                    err_flag <= 1'b1;     // 超时：写回没完成
                    err_code <= 8'd5;
                    fst      <= F_FIN;
                end
            end
            F_FIN: begin
                fst <= F_IDLE;
            end
            default: fst <= F_IDLE;
            endcase
        end
    end

    // ------------------------------------------------------------------
    // ---- 调试计数器（2026-10-28）：把链内部 valid/ready 的出现次数数出来 ----
    reg [31:0] thv_cnt;    // TopHat → CFAR 的 valid 拍数
    reg [31:0] cfv_cnt;    // CFAR → CCL 的 valid 拍数
    reg [15:0] cfrdy_cnt;  // CFAR 的 i_ready 拍数（= 图像列拍数）
    reg [15:0] chrdy_cnt;  // 链路入口 ready 拍数
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            thv_cnt   <= 32'd0;
            cfv_cnt   <= 32'd0;
            cfrdy_cnt <= 16'd0;
            chrdy_cnt <= 16'd0;
        end else if (!chain_rst_n) begin
            thv_cnt   <= 32'd0;
            cfv_cnt   <= 32'd0;
            cfrdy_cnt <= 16'd0;
            chrdy_cnt <= 16'd0;
        end else begin
            if (cha_thv)   thv_cnt   <= thv_cnt   + 32'd1;
            if (cha_cfv)   cfv_cnt   <= cfv_cnt   + 32'd1;
            if (cha_cfrdy) cfrdy_cnt <= cfrdy_cnt + 16'd1;
            if (cha_chrdy) chrdy_cnt <= chrdy_cnt + 16'd1;
        end
    end

    // LED：led[0] 心跳，led[3:1] 本帧候选数
    // ------------------------------------------------------------------
    reg [27:0] hb;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) hb <= 28'd0;
        else        hb <= hb + 28'd1;
    end

    assign led[0]   = hb[26];
    assign led[3:1] = (n_cand_r > 8'd7) ? 3'd7 : n_cand_r[2:0];

    // ---- 调试探针赋值（此处所有寄存器均已声明）----
    assign dbg_pcount = pcount;
    assign dbg_stat1  = {fifo_level[15:0], 5'd0, fst, err_code};
    assign dbg_ccl    = {8'd0, ch_dbg_px, 3'd0, ch_dbg_state};
    assign dbg_hand   = {ocount, ch_o_valid, rd_done, rd_error,
                         wr_done, wr_error, 18'd0};
    assign dbg_thv    = thv_cnt;
    assign dbg_cfv    = cfv_cnt;
    assign dbg_rdy    = {cfrdy_cnt, chrdy_cnt};

    // ---- 候选表寄存器镜像（声明在文件头，赋值放这里）----
    assign st_mirror = {1'b1, err_flag, 14'd0, frame_id};
    assign cand_rdata = cand_ram[cand_rd_idx];   // 异步读 -> LUTRAM
    assign fsm_snap  = {ocount, fst, wr_done, wr_error, rd_done, rd_error, 16'd0};
endmodule
