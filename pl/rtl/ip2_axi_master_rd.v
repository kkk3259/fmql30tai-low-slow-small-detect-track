// ip2_axi_master_rd.v —— AXI4 读主机：把 DDR 里的灰度帧读成 8 bit 像素流
//
// 作用：PS 把一帧 640×360 灰度图放在 DDR（默认 0x30100000），本模块按 AXI4 读出来，
//       转成 valid/ready 像素流送给 IP2（Top-Hat -> CFAR -> CCL）。
//
// 结构：
//   AR 通道：每突发 256 B（32 拍 × 8 B），一帧 230,400 B = 900 个突发。
//            230400 = 900 × 256，且帧基址 4 KB 对齐 → 突发永不跨 4 KB 边界。
//   R  通道：收到的 8 B 字写进 512 B FIFO（64 字）。
//   出口：FIFO -> 取一个 64 bit 字，按字节 0..7 顺序输出。
//
// 反压：出口 o_ready 直接来自 IP2 的 i_ready。CFAR 在虚拟光栅的 PAD 列会拉低 i_ready
//       （每行 30 拍），FIFO 吸收这段停顿，不会丢像素。
//
// ⚠️ Verific 推断 RAM 的硬性要求：FIFO 存储器的写必须放在**独立 always 块**里，
//    不能塞进状态机 case，否则 elaborate 报 ELAB-E-353 "Failed to dissolve the memory"。
module ip2_axi_master_rd #(
    parameter FIFO_AW = 6,      // FIFO 深度 2^6 = 64 个 64bit 字 = 512 B
    parameter BURST   = 32      // 每个 AXI 突发 32 拍 × 8 B = 256 B
)(
    input  wire        clk,
    input  wire        rst_n,
    // ---- 控制 ----
    input  wire        start,       // 单拍脉冲，启动一次整帧读取
    input  wire [31:0] base_addr,   // 帧起始物理地址
    input  wire [31:0] n_bytes,     // 要读的字节数（8 的倍数；640×360 → 230400）
    output reg         busy,
    output reg         done,        // 所有字都收到了（单拍/电平）
    output reg         error,       // 收到 RRESP != OKAY
    // ---- 像素流输出 ----
    output wire [7:0]  o_data,
    output wire        o_valid,
    input  wire        o_ready,
    // ---- AXI4 读地址通道 ----
    output reg  [31:0] m_araddr,
    output reg  [7:0]  m_arlen,
    output wire [2:0]  m_arsize,
    output wire [1:0]  m_arburst,
    output reg         m_arvalid,
    input  wire        m_arready,
    // ---- AXI4 读数据通道 ----
    input  wire [63:0] m_rdata,
    input  wire [1:0]  m_rresp,
    input  wire        m_rlast,
    input  wire        m_rvalid,
    output wire        m_rready
);
    assign m_arsize  = 3'd3;    // 每拍 8 字节
    assign m_arburst = 2'd1;    // INCR

    localparam FIFO_D = (1 << FIFO_AW);

    // ------------------------------------------------------------------
    // FIFO：64bit × 64
    // ------------------------------------------------------------------
    reg  [63:0]       fifo_mem [0:FIFO_D-1];
    reg  [FIFO_AW:0]  wr_ptr, rd_ptr, cnt;

    wire fifo_wr = m_rvalid && m_rready;
    wire fifo_rd;
    wire [63:0] fifo_dout = fifo_mem[rd_ptr[FIFO_AW-1:0]];

    assign m_rready = (cnt != FIFO_D);          // 有空间就收
    wire fifo_empty = (cnt == 0);

    // 独立写块（RAM 推断要求）
    always @(posedge clk) begin
        if (fifo_wr) fifo_mem[wr_ptr[FIFO_AW-1:0]] <= m_rdata;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= {(FIFO_AW+1){1'b0}};
            rd_ptr <= {(FIFO_AW+1){1'b0}};
            cnt    <= {(FIFO_AW+1){1'b0}};
        end else begin
            if (fifo_wr) wr_ptr <= wr_ptr + 1'b1;
            if (fifo_rd) rd_ptr <= rd_ptr + 1'b1;
            case ({fifo_wr, fifo_rd})
                2'b10:   cnt <= cnt + 1'b1;
                2'b01:   cnt <= cnt - 1'b1;
                default: cnt <= cnt;
            endcase
        end
    end

    // ------------------------------------------------------------------
    // 字节出口：一次取一个 64bit 字，按字节 0..7 顺序吐出
    // ------------------------------------------------------------------
    reg  [63:0] hold;
    reg  [2:0]  bidx;
    reg         hvalid;

    assign fifo_rd = (!hvalid) && (!fifo_empty);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            hold   <= 64'd0;
            bidx   <= 3'd0;
            hvalid <= 1'b0;
        end else if (start) begin
            // 新一帧从字节 0 开始
            hold   <= 64'd0;
            bidx   <= 3'd0;
            hvalid <= 1'b0;
        end else if (!hvalid) begin
            if (!fifo_empty) begin
                hold   <= fifo_dout;
                bidx   <= 3'd0;
                hvalid <= 1'b1;
            end
        end else if (o_ready) begin
            if (bidx == 3'd7) hvalid <= 1'b0;
            else              bidx   <= bidx + 3'd1;
        end
    end

    assign o_data  = hold[{bidx, 3'b000} +: 8];
    assign o_valid = hvalid;

    // ------------------------------------------------------------------
    // AR / R 状态机
    // ------------------------------------------------------------------
    reg  [31:0] cur_addr;
    reg  [31:0] words_total;    // 一帧共多少个 8B 字
    reg  [31:0] words_got;      // 已收到多少个字
    reg  [15:0] bursts_total;
    reg  [15:0] bursts_left;
    reg         ar_outstanding;

    wire [FIFO_AW:0] room = FIFO_D - cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy           <= 1'b0;
            done           <= 1'b0;
            error          <= 1'b0;
            m_arvalid      <= 1'b0;
            m_araddr       <= 32'd0;
            m_arlen        <= 8'd0;
            cur_addr       <= 32'd0;
            words_total    <= 32'd0;
            words_got      <= 32'd0;
            bursts_total   <= 16'd0;
            bursts_left    <= 16'd0;
            ar_outstanding <= 1'b0;
        end else if (start) begin
            busy           <= 1'b1;
            done           <= 1'b0;
            error          <= 1'b0;
            m_arvalid      <= 1'b0;
            m_araddr       <= base_addr;
            m_arlen        <= BURST[7:0] - 8'd1;
            cur_addr       <= base_addr;
            words_total    <= {n_bytes[31:3]};          // n_bytes / 8
            words_got      <= 32'd0;
            bursts_total   <= n_bytes[23:8];            // n_bytes / 256
            bursts_left    <= n_bytes[23:8];
            ar_outstanding <= 1'b0;
        end else if (busy) begin
            // ---- 发 AR ----
            if (m_arvalid && m_arready) begin
                m_arvalid      <= 1'b0;
                bursts_left    <= bursts_left - 16'd1;
                cur_addr       <= cur_addr + 32'd256;
                ar_outstanding <= 1'b1;
            end else if ((bursts_left != 16'd0) && !ar_outstanding &&
                         (room >= BURST[FIFO_AW:0])) begin
                m_arvalid <= 1'b1;
                m_araddr  <= cur_addr;
            end

            // ---- 收 R ----
            if (fifo_wr) begin
                words_got <= words_got + 32'd1;
                if (m_rresp != 2'd0) error <= 1'b1;
                if (m_rlast) ar_outstanding <= 1'b0;
                if (words_got == (words_total - 32'd1)) begin
                    busy <= 1'b0;
                    done <= 1'b1;
                end
            end
        end
    end
endmodule
