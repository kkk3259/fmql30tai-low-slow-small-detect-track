// ip2_axi_master_wr.v —— AXI4 写主机：把候选表 + 状态字写回 DDR
//
// 作用：CCL 输出的 36 字节候选表 + 4 字节状态字，由本模块写成两个 AXI4 写事务：
//   事务 1：base_addr + 0x00，5 拍（36 B = 4×8 B + 4 B），最后一拍 wstrb 只写低 4 字节
//   事务 2：base_addr + 0x40，1 拍（4 B 状态字）
// 分两个事务是为了不踩到 +0x40 之后 PS 侧可能放的其它字段。
//
// 布局（与 docs/14-PS-PL接口约定.md §2 一致）：
//   +0x00 ~ +0x23 : 36 B 候选表  [0]=n_cand，之后每候选 7 B：x_hi,x_lo,y_hi,y_lo,0,area,peak
//   +0x40         : 4 B 状态字  {bit31 done, bit30 error, bit15:0 frame_id}
module ip2_axi_master_wr (
    input  wire         clk,
    input  wire         rst_n,
    // ---- 控制 ----
    input  wire         start,        // 单拍脉冲
    input  wire [31:0]  base_addr,    // 输出区基址（默认 0x31000000）
    input  wire [287:0] cand_bytes,   // 36 B 候选表，cand_bytes[7:0] = byte0
    input  wire [31:0]  status_word,  // 状态字
    output reg          busy,
    output reg          done,         // 写完两笔后拉高
    output reg          error,        // 收到 BRESP != OKAY
    // ---- AXI4 写地址通道 ----
    output reg  [31:0]  m_awaddr,
    output reg  [7:0]   m_awlen,
    output wire [2:0]   m_awsize,
    output wire [1:0]   m_awburst,
    output reg          m_awvalid,
    input  wire         m_awready,
    // ---- AXI4 写数据通道 ----
    output wire [63:0]  m_wdata,
    output wire [7:0]   m_wstrb,
    output wire         m_wlast,
    output reg          m_wvalid,
    input  wire         m_wready,
    // ---- AXI4 写响应通道 ----
    input  wire [1:0]   m_bresp,
    input  wire         m_bvalid,
    output wire         m_bready
);
    assign m_awsize  = 3'd3;    // 8 字节/拍
    assign m_awburst = 2'd1;    // INCR
    assign m_bready  = 1'b1;    // 永远准备收响应

    localparam S_IDLE = 3'd0,
               S_AW_C = 3'd1,   // 事务1：发 AW（候选表）
               S_W_C  = 3'd2,   // 事务1：发 5 拍数据
               S_B_C  = 3'd3,   // 事务1：等 B
               S_AW_S = 3'd4,   // 事务2：发 AW（状态字）
               S_W_S  = 3'd5,   // 事务2：发 1 拍数据
               S_B_S  = 3'd6,   // 事务2：等 B
               S_DONE = 3'd7;

    reg [2:0] st;
    reg [2:0] beat;             // 事务1 的第几拍（0..4）

    // 事务1 的每拍数据/选通（组合，避免寄存器更新出错）
    reg [63:0] wd_c;
    reg [7:0]  ws_c;
    reg        wl_c;
    always @(*) begin
        case (beat)
            3'd0:    begin wd_c = cand_bytes[ 63:  0];     ws_c = 8'hFF; wl_c = 1'b0; end
            3'd1:    begin wd_c = cand_bytes[127: 64];     ws_c = 8'hFF; wl_c = 1'b0; end
            3'd2:    begin wd_c = cand_bytes[191:128];     ws_c = 8'hFF; wl_c = 1'b0; end
            3'd3:    begin wd_c = cand_bytes[255:192];     ws_c = 8'hFF; wl_c = 1'b0; end
            3'd4:    begin wd_c = {32'd0, cand_bytes[287:256]}; ws_c = 8'h0F; wl_c = 1'b1; end
            default: begin wd_c = 64'd0;                   ws_c = 8'h00; wl_c = 1'b0; end
        endcase
    end

    // 事务2（状态字）优先，其余用事务1 的拍数据
    assign m_wdata = (st == S_W_S) ? {32'd0, status_word} : wd_c;
    assign m_wstrb = (st == S_W_S) ? 8'h0F               : ws_c;
    assign m_wlast = (st == S_W_S) ? 1'b1                : wl_c;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st        <= S_IDLE;
            beat      <= 3'd0;
            busy      <= 1'b0;
            done      <= 1'b0;
            error     <= 1'b0;
            m_awvalid <= 1'b0;
            m_awaddr  <= 32'd0;
            m_awlen   <= 8'd0;
            m_wvalid  <= 1'b0;
        end else begin
            case (st)
            S_IDLE: begin
                if (start && !busy) begin
                    busy      <= 1'b1;
                    done      <= 1'b0;
                    error     <= 1'b0;
                    beat      <= 3'd0;
                    m_awaddr  <= base_addr;
                    m_awlen   <= 8'd4;          // 5 拍
                    m_awvalid <= 1'b1;
                    st        <= S_AW_C;
                end
            end
            S_AW_C: begin
                if (m_awready) begin
                    m_awvalid <= 1'b0;
                    beat      <= 3'd0;
                    m_wvalid  <= 1'b1;
                    st        <= S_W_C;
                end
            end
            S_W_C: begin
                if (m_wready) begin
                    if (beat == 3'd4) begin
                        m_wvalid <= 1'b0;
                        st       <= S_B_C;
                    end else begin
                        beat <= beat + 3'd1;
                    end
                end
            end
            S_B_C: begin
                if (m_bvalid) begin
                    if (m_bresp != 2'd0) error <= 1'b1;
                    m_awaddr  <= base_addr + 32'd64;   // +0x40 状态字
                    m_awlen   <= 8'd0;                 // 1 拍
                    m_awvalid <= 1'b1;
                    st        <= S_AW_S;
                end
            end
            S_AW_S: begin
                if (m_awready) begin
                    m_awvalid <= 1'b0;
                    m_wvalid  <= 1'b1;
                    st        <= S_W_S;
                end
            end
            S_W_S: begin
                if (m_wready) begin
                    m_wvalid <= 1'b0;
                    st       <= S_B_S;
                end
            end
            S_B_S: begin
                if (m_bvalid) begin
                    if (m_bresp != 2'd0) error <= 1'b1;
                    busy <= 1'b0;
                    done <= 1'b1;
                    st   <= S_DONE;
                end
            end
            S_DONE: begin
                // done 是电平，等到 start 收回后回 IDLE 并清 done，
                // 否则下一帧的 start 会被 !done 条件挡住（曾经在这里死锁过）
                if (!start) begin
                    done <= 1'b0;
                    st   <= S_IDLE;
                end
            end
            default: st <= S_IDLE;
            endcase
        end
    end
endmodule
