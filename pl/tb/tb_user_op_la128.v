//=============================================================================
// tb_user_op_la.v —— 离线定位适配层数据通路：跑一小段，直接把片上 LA 的内容打出来
//   clk=200MHz(hp_clk)  ra_clk=50MHz(gp_clk)
//   与硬件等价：写 FRAME_ADDR/START -> PL 读帧 -> 轮询 STATUS -> 读候选
//   关键：不需要走寄存器读 LA，直接层次化访问 dut.la_mem[]，快得多
//=============================================================================
`timescale 1ns / 1ps

module tb_user_op_la128;
    localparam W    = 128;
    localparam H    = 64;
    localparam NPIX = W * H;

    reg clk = 0, ra_clk = 0, rst_n = 0, ra_rst_n = 0;
    always #2.5 clk    = ~clk;
    always #10  ra_clk = ~ra_clk;

    reg  [31:0] ra_awaddr = 0, ra_awdata = 0;
    reg         ra_awvalid = 0;
    wire        ra_awready;
    reg  [31:0] ra_araddr = 0;
    reg         ra_arvalid = 0;
    wire        ra_arready;
    wire [31:0] ra_rdata;
    wire        ra_rvalid;
    reg         ra_rready = 1;

    wire [31:0]  itf_awaddr;
    wire [511:0] itf_awdata;
    wire         itf_awvalid;
    reg          itf_awready = 0;
    wire [31:0]  itf_araddr;
    wire         itf_arvalid;
    reg          itf_arready = 1;
    reg  [511:0] itf_rdata = 0;
    reg          itf_rvalid = 0;
    wire         itf_rready;
    wire [1:0]   led;

    reg [7:0] mem [0:NPIX+4096];

    ip2_user_op #(.W(W), .H(H), .SE(5), .MAX_CAND(16)) dut (
        .itf_ra_awaddr(ra_awaddr), .itf_ra_awdata(ra_awdata),
        .itf_ra_awvalid(ra_awvalid), .itf_ra_awready(ra_awready),
        .itf_ra_araddr(ra_araddr), .itf_ra_arvalid(ra_arvalid),
        .itf_ra_arready(ra_arready), .itf_ra_rdata(ra_rdata),
        .itf_ra_rvalid(ra_rvalid), .itf_ra_rready(ra_rready),
        .itf_awaddr(itf_awaddr), .itf_awdata(itf_awdata),
        .itf_awvalid(itf_awvalid), .itf_awready(itf_awready),
        .itf_araddr(itf_araddr), .itf_arvalid(itf_arvalid),
        .itf_arready(itf_arready), .itf_rdata(itf_rdata),
        .itf_rvalid(itf_rvalid), .itf_rready(itf_rready),
        .led(led),
        .clk(clk), .ra_clk(ra_clk), .rst_n(rst_n), .ra_rst_n(ra_rst_n)
    );

    // ---- 512 位数据口从机：一次返回 64 字节 ----
    integer dl;
    always @(posedge clk) begin
        if (itf_arvalid && itf_arready && !itf_rvalid) begin
            itf_arready <= 1'b0;
            for (dl = 0; dl < 64; dl = dl + 1)
                itf_rdata[dl*8 +: 8] <= mem[(itf_araddr + dl) % (NPIX+4096)];
            itf_rvalid <= 1'b1;
        end else if (itf_rvalid) begin
            itf_rvalid  <= 1'b0;
            itf_arready <= 1'b1;
        end
    end

    // ---- 寄存器口任务 ----
    task reg_write(input [31:0] a, input [31:0] d);
    begin
        @(posedge ra_clk); ra_awaddr <= a; ra_awdata <= d; ra_awvalid <= 1;
        @(posedge ra_clk); while (!ra_awready) @(posedge ra_clk);
        ra_awvalid <= 0;
        @(posedge ra_clk);
    end endtask

    task reg_read(input [31:0] a, output [31:0] d);
    begin
        @(posedge ra_clk); ra_araddr <= a; ra_arvalid <= 1;
        @(posedge ra_clk); while (!ra_arready) @(posedge ra_clk);
        ra_arvalid <= 0;
        while (!ra_rvalid) @(posedge ra_clk);
        d = ra_rdata;
        @(posedge ra_clk);
    end endtask

    integer i, j, k;
    reg [31:0] v, st;
    reg [31:0] ev;

    initial begin
        // 帧：黑底 + 一个 12x12 白块在 (100,80)
        for (i = 0; i < NPIX+4096; i = i + 1) mem[i] = 8'd0;
        for (i = 30; i < 42; i = i + 1)
            for (j = 40; j < 52; j = j + 1)
                mem[i*W + j] = 8'd200;

        rst_n = 0; ra_rst_n = 0;
        repeat (20) @(posedge clk);
        rst_n = 1; ra_rst_n = 1;
        repeat (20) @(posedge clk);

        reg_read(32'h14, v);              // VERSION
        $display("VERSION = %08h", v);
        reg_write(32'h04, 32'd0);         // FRAME_ADDR = 0
        reg_write(32'h08, 32'd0);         // RESULT_ADDR
        reg_write(32'h00, 32'd1);         // START

        // 跑 120us（让检测器有机会跑完一帧）
        repeat (120000) @(posedge clk);

        reg_read(32'h0C, st);
        $display("STATUS = %08h  (n_cand=%0d done=%0d err=%0d)", st, st[15:8], st[1], st[2]);
        reg_read(32'h90, v); $display("DBG_AR = %0d", v);
        reg_read(32'h94, v); $display("DBG_RV = %0d", v);
        reg_read(32'h98, v); $display("DBG_WD = %0d", v);
        reg_read(32'h9C, v); $display("DBG_ST = %08h", v);
        reg_read(32'hA8, v); $display("LA_ST  = %08h  (frozen=%0d wp=%0d)", v, v[31], v[15:8]);

        $display("---- LA 事件（最近 32 条）----");
        k = dut.la_wp;
        for (i = 1; i <= 32; i = i + 1) begin
            if (i <= k) begin
                ev = dut.la_mem[(k - i) & 255];
                $display("  [-%0d] tag=%0d  %08h", i, ev[31:28], ev);
            end
        end

        $display("---- 候选窗口前 8 个字 ----");
        for (i = 0; i < 8; i = i + 1) begin
            reg_write(32'h10, i);
            reg_read(32'h10, v);
            $display("  cand[%0d] = %08h", i, v);
        end
        $display("VERDICT DONE");
        $finish;
    end

    // 每 20000 拍打印内部进度，定位卡在哪一级
    integer pm;
    initial begin
        for (pm = 0; pm < 6; pm = pm + 1) begin
            #(20000 * 5);
            $display("T=%0t pcount=%0d ocount=%0d fst=%0d thv=%0d cfv=%0d cfrdy=%0d",
                     $time, dut.u_ip2.pcount, dut.u_ip2.ocount, dut.u_ip2.fst,
                     dut.u_ip2.thv_cnt, dut.u_ip2.cfv_cnt, dut.u_ip2.cfrdy_cnt);
        end
    end

    initial begin
        #2000000;
        $display("TB TIMEOUT");
        $finish;
    end
endmodule
