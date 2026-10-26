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
//   0x10 FRAME_ID     W  帧号（低 16 位写进状态字回传给 PS）
//   0x14 VERSION      R  0x0001_0000
module ip2_axi_top #(
    parameter W = 640,
    parameter H = 360,
    parameter MAX_CAND = 5,
    parameter [31:0] DEF_FRAME_ADDR  = 32'h3010_0000,
    parameter [31:0] DEF_RESULT_ADDR = 32'h3100_0000
)(
    input  wire        clk,
    input  wire        rst_n,
    output wire [3:0]  led,

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
                    6'h10: frame_id    <= wdata_l[15:0];
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
    reg  [5:0] araddr_l;
    assign s_axi_arready = !r_pend && !s_axi_rvalid;
    assign s_axi_rresp   = 2'b00;

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
                    6'h10:   s_axi_rdata <= {16'd0, frame_id};
                    6'h14:   s_axi_rdata <= 32'h0001_0000;
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
    reg [5:0]  ocount;          // 已收候选表字节数
    reg [287:0] cand_buf;       // 36 B 候选表
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
    wire         chain_en  = (fst == F_FEED);
    wire         fifo_pop  = fifo_valid && ch_i_ready && chain_en;

    assign rd_ready = !fifo_full;                       // 只受帧缓冲满反压

    ip2_pix_fifo #(.DEPTH(262144), .AW(AW_F)) u_pixfifo (
        .clk(clk), .rst_n(rst_n),
        .wr_en(rd_valid), .wr_data(rd_data), .wr_full(fifo_full),
        .rd_data(fifo_data), .rd_valid(fifo_valid), .rd_ready(ch_i_ready && chain_en),
        .level(fifo_level)
    );

    ip2_axi_master_rd #(.FIFO_AW(6), .BURST(32)) u_rd (
        .clk(clk), .rst_n(rst_n),
        .start(rd_start),
        .base_addr(frame_addr),
        .n_bytes(NPIX[31:0]),
        .busy(rd_busy), .done(rd_done), .error(rd_error),
        .o_data(rd_data), .o_valid(rd_valid), .o_ready(rd_ready),
        .m_araddr(m_axi_araddr), .m_arlen(m_axi_arlen),
        .m_arsize(m_axi_arsize), .m_arburst(m_axi_arburst),
        .m_arvalid(m_axi_arvalid), .m_arready(m_axi_arready),
        .m_rdata(m_axi_rdata), .m_rresp(m_axi_rresp), .m_rlast(m_axi_rlast),
        .m_rvalid(m_axi_rvalid), .m_rready(m_axi_rready)
    );

    ip2_top_stream #(.W(W), .H(H), .MAX_CAND(MAX_CAND)) u_chain (
        .clk(clk), .rst_n(chain_rst_n),
        .i_data(fifo_data),
        .i_valid(fifo_valid && chain_en),
        .i_ready(ch_i_ready),
        .o_data(ch_o_data), .o_valid(ch_o_valid), .o_ready(1'b1)
    );

    ip2_axi_master_wr u_wr (
        .clk(clk), .rst_n(rst_n),
        .start(wr_start),
        .base_addr(result_addr),
        .cand_bytes(cand_buf),
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
    assign wr_start = (fst == F_WAIT) && (ocount >= 6'd36) && !wr_busy && !wr_done;

    // 帧缓冲是否已装满（读主机把 NPIX 个像素全部搬进 FIFO/帧缓存）
    wire frame_loaded = rd_done && (fifo_level >= NPIX[AW_F-1:0]);

    // 候选表收集：CCL 在 S_DONE 里 o_valid 一直高，只收前 36 字节
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ocount   <= 6'd0;
            cand_buf <= 288'd0;
        end else if (fst == F_RST) begin
            // 注意：这里只能用 F_RST 清，不能用 !chain_rst_n。
            // chain_rst_n 在 F_WRITE/F_FIN 也是 0，用它会把刚收好的 36 字节
            // 在写回之前清掉（表现为候选表全 0、只有状态字正常）。
            ocount   <= 6'd0;
            cand_buf <= 288'd0;
        end else if (ch_o_valid && (ocount < 6'd36)) begin
            cand_buf[{ocount, 3'b000} +: 8] <= ch_o_data;
            ocount <= ocount + 6'd1;
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
                if (rd_error) err_flag <= 1'b1;
                if (frame_loaded) begin
                    fst  <= F_FEED;
                    wdog <= 32'd0;
                end else if (wdog > 32'd12_000_000) begin
                    err_flag <= 1'b1;      // 读帧超时
                    fst      <= F_FIN;
                end
            end
            F_FEED: begin
                if (rd_error) err_flag <= 1'b1;
                if (pcount >= NPIX[31:0]) begin
                    fst  <= F_WAIT;
                    wdog <= 32'd0;
                end
            end
            F_WAIT: begin
                wdog <= wdog + 32'd1;
                if (ocount >= 6'd36) begin
                    n_cand_r <= cand_buf[7:0];
                    wdog     <= 32'd0;
                    fst      <= F_WRITE;
                end else if (wdog > 32'd8_000_000) begin
                    err_flag <= 1'b1;     // 超时：链路没吐完候选表
                    fst      <= F_FIN;
                end
            end
            F_WRITE: begin
                wdog <= wdog + 32'd1;
                if (wr_done) begin
                    if (wr_error) err_flag <= 1'b1;
                    done_flag <= 1'b1;
                    frm_cnt   <= frm_cnt + 8'd1;
                    fst       <= F_FIN;
                end else if (wdog > 32'd1_000_000) begin
                    err_flag <= 1'b1;     // 超时：写回没完成
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
    // LED：led[0] 心跳，led[3:1] 本帧候选数
    // ------------------------------------------------------------------
    reg [27:0] hb;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) hb <= 28'd0;
        else        hb <= hb + 28'd1;
    end

    assign led[0]   = hb[26];
    assign led[3:1] = (n_cand_r > 8'd7) ? 3'd7 : n_cand_r[2:0];
endmodule
