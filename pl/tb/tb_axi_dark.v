// tb_axi_top.v —— ip2_axi_top 全链路仿真（带行为级 AXI4 从机 = 内存模型）
//
// 验证目标：
//   1. PS 视角：AXI-Lite 写 FRAME_ADDR / RESULT_ADDR / FRAME_ID / CTRL.start，轮询 STATUS.done
//   2. 数据面：读主机从「内存模型」按 AXI4 读 128×72 帧 -> IP2 链 -> 写主机写回候选表
//   3. 结果：候选表 36 字节与 Python 参考（ref_integration.hex）逐字节一致
//
// 运行（cwd = pl/sim，输入文件在那里）：
//   iverilog -g2005 -o axi_top.vvp ../tb/tb_axi_top.v ../rtl/ip2_axi_top.v \
//            ../rtl/ip2_axi_master_rd.v ../rtl/ip2_axi_master_wr.v \
//            ../rtl/ip2_top_stream.v ../rtl/tophat_5x5_stream.v ../rtl/win5.v \
//            ../rtl/cfar_threshold_stream.v ../rtl/candidate_extract_stream.v
//   vvp axi_top.vvp
`timescale 1ns/1ps

module tb_axi_dark;
    localparam W = 640;
    localparam H = 360;
    localparam NPIX = W * H;                 // 9216

    localparam [31:0] FRAME_ADDR = 32'h3010_0000;
    localparam [31:0] RES_ADDR   = 32'h3100_0000;
    localparam MEMSZ = 24'h40_0000;          // 4 MB 内存模型（640x360 帧 230400 B）

    // ---------------- 时钟 / 复位 ----------------
    reg clk = 1'b0;
    reg rst_n = 1'b0;
    always #5 clk = ~clk;

    // ---------------- 内存模型 ----------------
    reg [7:0] mem [0:MEMSZ-1];
    reg [7:0] in_mem [0:NPIX-1];
    reg [7:0] ref_mem [0:63];
    integer    ii, b0;
    integer    ci, q, n_total, cx, cy, area, peak;
    reg [7:0]  cbyte [0:6];
    integer    n_ref_bytes = 36;   // 参考表有效字节数（1 + 5*7）

    integer i;
    initial begin
        for (i = 0; i < MEMSZ; i = i + 1) mem[i] = 8'h00;
        $readmemh("target640_dark.hex", in_mem);
        for (ii = 0; ii < 64; ii = ii + 1) ref_mem[ii] = 0;
        // 帧放到地址 0x30100000 -> mem 索引 0x100000
        for (i = 0; i < NPIX; i = i + 1) mem[24'h10_0000 + i] = in_mem[i];
    end

    // ---------------- DUT 端口 ----------------
    wire [3:0] led;

    // AXI4-Lite 主（tb 扮演 PS）
    reg  [7:0]  s_awaddr  = 6'd0;
    reg         s_awvalid = 1'b0;
    wire        s_awready;
    reg  [31:0] s_wdata   = 32'd0;
    reg  [3:0]  s_wstrb   = 4'hF;
    reg         s_wvalid  = 1'b0;
    wire        s_wready;
    wire [1:0]  s_bresp;
    wire        s_bvalid;
    reg         s_bready  = 1'b1;
    reg  [7:0]  s_araddr  = 6'd0;
    reg         s_arvalid = 1'b0;
    wire        s_arready;
    wire [31:0] s_rdata;
    wire [1:0]  s_rresp;
    wire        s_rvalid;
    reg         s_rready  = 1'b1;

    // AXI4 主（DUT）-> 从机模型
    wire [31:0] m_araddr;
    wire [7:0]  m_arlen;
    wire [2:0]  m_arsize;
    wire [1:0]  m_arburst;
    wire        m_arvalid;
    wire        m_arready;
    wire [63:0] m_rdata;
    wire [1:0]  m_rresp;
    wire        m_rlast;
    wire        m_rvalid;
    wire        m_rready;

    wire [31:0] m_awaddr;
    wire [7:0]  m_awlen;
    wire [2:0]  m_awsize;
    wire [1:0]  m_awburst;
    wire        m_awvalid;
    wire        m_awready;
    wire [63:0] m_wdata;
    wire [7:0]  m_wstrb;
    wire        m_wlast;
    wire        m_wvalid;
    wire        m_wready;
    wire [1:0]  m_bresp;
    wire        m_bvalid;
    wire        m_bready_s;

    ip2_axi_top #(
        .W(W), .H(H), .MAX_CAND(64), .MODE(1), .SE(21),
        .DEF_FRAME_ADDR(FRAME_ADDR), .DEF_RESULT_ADDR(RES_ADDR)
    ) dut (
        .clk(clk), .rst_n(rst_n), .led(led),
        .s_axi_awaddr(s_awaddr), .s_axi_awvalid(s_awvalid), .s_axi_awready(s_awready),
        .s_axi_wdata(s_wdata), .s_axi_wstrb(s_wstrb), .s_axi_wvalid(s_wvalid),
        .s_axi_wready(s_wready), .s_axi_bresp(s_bresp), .s_axi_bvalid(s_bvalid),
        .s_axi_bready(s_bready),
        .s_axi_araddr(s_araddr), .s_axi_arvalid(s_arvalid), .s_axi_arready(s_arready),
        .s_axi_rdata(s_rdata), .s_axi_rresp(s_rresp), .s_axi_rvalid(s_rvalid),
        .s_axi_rready(s_rready),
        .m_axi_araddr(m_araddr), .m_axi_arlen(m_arlen), .m_axi_arsize(m_arsize),
        .m_axi_arburst(m_arburst), .m_axi_arvalid(m_arvalid), .m_axi_arready(m_arready),
        .m_axi_rdata(m_rdata), .m_axi_rresp(m_rresp), .m_axi_rlast(m_rlast),
        .m_axi_rvalid(m_rvalid), .m_axi_rready(m_rready),
        .m_axi_awaddr(m_awaddr), .m_axi_awlen(m_awlen), .m_axi_awsize(m_awsize),
        .m_axi_awburst(m_awburst), .m_axi_awvalid(m_awvalid), .m_axi_awready(m_awready),
        .m_axi_wdata(m_wdata), .m_axi_wstrb(m_wstrb), .m_axi_wlast(m_wlast),
        .m_axi_wvalid(m_wvalid), .m_axi_wready(m_wready),
        .m_axi_bresp(m_bresp), .m_axi_bvalid(m_bvalid), .m_axi_bready(m_bready_s)
    );

    // ==================================================================
    // AXI4 从机模型：读通道
    // ==================================================================
    reg        rd_active;
    reg [23:0] rd_base;
    reg [7:0]  rd_arlen, rd_beat;
    reg        s_rvalid_i, s_rlast_i;
    reg [63:0] rd_word;
    integer    kk;

    assign m_arready = !rd_active;
    assign m_rvalid  = s_rvalid_i;
    assign m_rlast   = s_rlast_i;
    assign m_rdata   = rd_word;
    assign m_rresp   = 2'b00;

    // 注意：这里【不能】用 always @(*) + 数组索引。
    // iverilog 对 always @(*) 里带变量下标的数组读取会把 mem 的
    // 全部 1310720 个元素都加进敏感表，编译直接卡死（实测 >7 分钟无输出）。
    // 改用 function + 连续赋值：既是组合逻辑，又不会枚举数组敏感度。
    function [63:0] mem_word(input [23:0] base, input [7:0] beat);
        integer t;
        begin
            for (t = 0; t < 8; t = t + 1)
                mem_word[t*8 +: 8] = mem[base + beat * 8 + t[23:0]];
        end
    endfunction

    always @(rd_base or rd_beat) begin
        rd_word <= mem_word(rd_base, rd_beat);
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rd_active <= 1'b0;
            rd_base   <= 24'd0;
            rd_arlen  <= 8'd0;
            rd_beat   <= 8'd0;
            s_rvalid_i<= 1'b0;
            s_rlast_i <= 1'b0;
        end else if (!rd_active) begin
            s_rvalid_i <= 1'b0;
            s_rlast_i  <= 1'b0;
            if (m_arvalid && m_arready) begin
                rd_base    <= m_araddr[23:0];
                rd_arlen   <= m_arlen;
                rd_beat    <= 8'd0;
                rd_active  <= 1'b1;
                s_rvalid_i <= 1'b1;
                s_rlast_i  <= (m_arlen == 8'd0);
            end
        end else if (s_rvalid_i && m_rready) begin
            if (rd_beat == rd_arlen) begin
                rd_active  <= 1'b0;
                s_rvalid_i <= 1'b0;
                s_rlast_i  <= 1'b0;
            end else begin
                rd_beat   <= rd_beat + 8'd1;
                s_rlast_i <= ((rd_beat + 8'd1) == rd_arlen);
            end
        end
    end

    // ==================================================================
    // AXI4 从机模型：写通道
    // ==================================================================
    reg        s_awready_i, s_wready_i, s_bvalid_i;
    reg [23:0] wr_base;
    reg [7:0]  wr_beat;
    integer    jj;

    assign m_awready = s_awready_i;
    assign m_wready  = s_wready_i;
    assign m_bvalid  = s_bvalid_i;
    assign m_bresp   = 2'b00;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s_awready_i <= 1'b1;
            s_wready_i  <= 1'b1;
            s_bvalid_i  <= 1'b0;
            wr_base     <= 24'd0;
            wr_beat     <= 8'd0;
        end else begin
            // AW
            if (s_awready_i && m_awvalid) begin
                wr_base     <= m_awaddr[23:0];
                wr_beat     <= 8'd0;
                s_awready_i <= 1'b0;
            end
            // W
            if (s_wready_i && m_wvalid) begin
                for (jj = 0; jj < 8; jj = jj + 1)
                    if (m_wstrb[jj])
                        mem[wr_base + {8'd0, wr_beat} * 8 + jj] <= m_wdata[jj*8 +: 8];
                wr_beat <= wr_beat + 8'd1;
                if (m_wlast) begin
                    s_wready_i <= 1'b0;
                    s_bvalid_i <= 1'b1;
                end
            end
            // B
            if (s_bvalid_i && m_bready_s) begin
                s_bvalid_i  <= 1'b0;
                s_awready_i <= 1'b1;
                s_wready_i  <= 1'b1;
            end
        end
    end

    // ==================================================================
    // AXI-Lite 主机任务（tb 扮演 PS）
    // ==================================================================
    task axi_write(input [7:0] a, input [31:0] d);
        begin
            @(negedge clk);
            s_awaddr  = a;
            s_awvalid = 1'b1;
            s_wdata   = d;
            s_wstrb   = 4'hF;
            s_wvalid  = 1'b1;
            // 等握手
            while (!(s_awready && s_wready)) @(negedge clk);
            @(posedge clk);           // 握手发生在这一拍
            @(negedge clk);
            s_awvalid = 1'b0;
            s_wvalid  = 1'b0;
            while (!s_bvalid) @(negedge clk);
            @(negedge clk);
        end
    endtask

    task axi_read(input [7:0] a, output [31:0] d);
        begin
            @(negedge clk);
            s_araddr  = a;
            s_arvalid = 1'b1;
            while (!s_arready) @(negedge clk);
            @(posedge clk);
            @(negedge clk);
            s_arvalid = 1'b0;
            while (!s_rvalid) @(negedge clk);
            d = s_rdata;
            @(negedge clk);
        end
    endtask

    // ==================================================================
    // 主流程
    // ==================================================================
    reg [31:0] st;
    integer    t, nloop, diffs, done_seen;
    integer    wi, bi, b_idx, n_words;
    reg [31:0] wd, w0, w1, w2, w3;
    reg [7:0]  got_byte, exp_byte;

    initial begin
        // 复位
        rst_n = 1'b0;
        repeat (10) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;
        repeat (10) @(posedge clk);

        // 配置并启动一帧
        axi_write(6'h04, FRAME_ADDR);
        axi_write(6'h08, RES_ADDR);
                axi_write(6'h00, 32'h0000_0001);   // start

        // 轮询 STATUS.done（bit1）
        done_seen = 0;
        for (nloop = 0; nloop < 4000; nloop = nloop + 1) begin
            repeat (200) @(posedge clk);
            axi_read(6'h0C, st);
            if (st[1] === 1'b1) begin
                done_seen = 1;
                nloop = 4000;
            end
        end
        repeat (20) @(posedge clk);

        if (!done_seen) begin
            $display("RESULT TIMEOUT: STATUS=0x%08x", st);
            $finish;
        end
        $display("STATUS = 0x%08x  (busy=%0d done=%0d err=%0d n_cand=%0d cap=%0d)",
                 st, st[0], st[1], st[2], st[15:8], st[23:16]);

        // 比对候选表：从索引窗口读（0x40 写索引 / 0x44 读数据）
        //   MAX_CAND=64 时缓冲区 = 1 + 64*7 = 449 字节，向上补齐到 452（113 个字）
        diffs = 0;
        n_words = (n_ref_bytes + 3) / 4;
        for (wi = 0; wi < n_words; wi = wi + 1) begin
            axi_write(6'h10, wi[31:0]);
            axi_read (6'h10, wd);
            for (bi = 0; bi < 4; bi = bi + 1) begin
                b_idx = wi*4 + bi;
                if (b_idx < n_ref_bytes) begin
                    got_byte = wd[bi*8 +: 8];
                    exp_byte = ref_mem[b_idx];
                    if (got_byte !== exp_byte) begin
                        diffs = diffs + 1;
                        if (diffs <= 10)
                            $display("  DIFF byte%0d got=%02X exp=%02X", b_idx, got_byte, exp_byte);
                    end
                end
            end
        end

        // ---- 打印全部候选（1 + n*7 字节）----
        n_total = st[15:8];
        if (n_total > 64) n_total = 64;
        $display("CAND n_cand=%0d", n_total);
        for (ci = 0; ci < n_total; ci = ci + 1) begin
            // 每个候选 7 字节，从字节 1 开始
            b0 = 1 + ci * 7;
            for (q = 0; q < 7; q = q + 1) cbyte[q] = 8'h00;
            for (q = 0; q < 7; q = q + 1) begin
                wi = (b0 + q) / 4;
                bi = (b0 + q) % 4;
                axi_write(6'h10, wi[31:0]);
                axi_read (6'h10, wd);
                cbyte[q] = wd[8*(3-bi) +: 8];
            end
            cx = {cbyte[0], cbyte[1]};
            cy = {cbyte[2], cbyte[3]};
            area = {cbyte[5]};
            peak = cbyte[6];
            $display("  #%0d  x=%0d y=%0d area=%0d peak=%0d", ci, cx, cy, area, peak);
        end
        $display("VERDICT TARGETS-DONE n_cand=%0d", n_total);
        $finish;
    end

    // 全局看门狗
    initial begin
        #50_000_000;
        $display("RESULT GLOBAL-TIMEOUT");
        $finish;
    end

    // ------------------------------------------------------------------
    // 像素流抽查：链路到底吃进了什么（FIFO 出队口）vs 内存原图
    // ------------------------------------------------------------------
    integer acnt;
    integer amis;
    integer bubbles;
    initial begin
        acnt = 0;
        amis = 0;
        bubbles = 0;
        wait (rst_n === 1'b1);
        forever begin
            @(posedge clk);
            // 链路正在喂帧、却拿不到有效像素 → 这个空拍会破坏窗口几何
            if (dut.fst == 3'd2 && !dut.fifo_valid && acnt < NPIX) bubbles = bubbles + 1;
            if (dut.fifo_pop) begin
                if (acnt < 8)
                    $display("  POP[%0d] got=%02X exp=%02X %s", acnt,
                             dut.fifo_data,
                             (acnt < NPIX) ? in_mem[acnt] : 8'h00,
                             (dut.fifo_data === in_mem[acnt]) ? "ok" : "MISMATCH");
                if (dut.fifo_data !== in_mem[acnt]) begin
                    amis = amis + 1;
                    if (amis <= 8)
                        $display("  POPMIS idx=%0d got=%02X exp=%02X", acnt,
                                 dut.fifo_data, in_mem[acnt]);
                end
                acnt = acnt + 1;
                if (acnt == NPIX)
                    $display("  === 链路吃进: %0d 个, 不一致 %0d 个, 中途空拍 %0d 次 ===",
                             acnt, amis, bubbles);
            end
        end
    end
endmodule
