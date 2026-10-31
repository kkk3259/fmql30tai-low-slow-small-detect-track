//=============================================================================
// tb_user_op_small.v —— 小尺寸（64x48）快速验证 ip2_user_op 的跨时钟域适配层
//   clk = 200 MHz（hp_clk），ra_clk = 50 MHz（gp_clk），核心自动降到 clk/4 = 50 MHz
//=============================================================================
`timescale 1ns / 1ps

module tb_user_op_mid;
    localparam W = 320;
    localparam H = 180;
    localparam NPIX = W * H;

    reg clk = 0, ra_clk = 0, rst_n = 0, ra_rst_n = 0;
    always #2.5 clk    = ~clk;      // 200 MHz
    always #10  ra_clk = ~ra_clk;   //  50 MHz

    // ---- 平台寄存器口 ----
    reg  [31:0] ra_awaddr = 0, ra_awdata = 0;
    reg         ra_awvalid = 0;
    wire        ra_awready;
    reg  [31:0] ra_araddr = 0;
    reg         ra_arvalid = 0;
    wire        ra_arready;
    wire [31:0] ra_rdata;
    wire        ra_rvalid;
    reg         ra_rready = 1;

    // ---- 平台数据口 ----
    wire [31:0]  itf_awaddr;
    wire [511:0] itf_awdata;
    wire         itf_awvalid;
    reg          itf_awready = 0;
    wire [31:0]  itf_araddr;
    wire         itf_arvalid;
    reg          itf_arready = 0;
    reg  [511:0] itf_rdata = 0;
    reg          itf_rvalid = 0;
    wire         itf_rready;

    wire [1:0] led;

    // ---- 帧内存 ----
    reg [7:0] mem [0:NPIX-1];

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

    // ---- 数据口从机：2 拍后返回 64 字节 ----
    integer dl;
    always @(posedge clk) begin
        if (itf_arvalid && itf_arready && !itf_rvalid) begin
            itf_arready <= 1'b0;
            for (dl = 0; dl < 64; dl = dl + 1)
                if (itf_araddr + dl < NPIX) itf_rdata[dl*8 +: 8] <= mem[itf_araddr + dl];
                else                        itf_rdata[dl*8 +: 8] <= 8'd0;
            itf_rvalid <= 1'b1;
        end else if (itf_rvalid) begin
            itf_rvalid  <= 1'b0;
            itf_arready <= 1'b1;
        end else begin
            itf_arready <= 1'b1;
        end
    end


    // ---- 诊断计数 ----
    integer n_ar = 0, n_r = 0, n_raaw = 0, n_raar = 0;
    always @(posedge clk) begin
        if (itf_arvalid && itf_arready) n_ar <= n_ar + 1;
        if (itf_rvalid)                 n_r  <= n_r + 1;
    end
    always @(posedge ra_clk) begin
        if (ra_awvalid && ra_awready) n_raaw <= n_raaw + 1;
        if (ra_arvalid && ra_arready) n_raar <= n_raar + 1;
    end
    initial begin
        #2_000_000;
        $display("[diag 2ms] ar=%0d r=%0d ra_aw=%0d ra_ar=%0d led=%b", n_ar, n_r, n_raaw, n_raar, led);
    end

    // ---- 寄存器任务 ----
    task reg_write(input [31:0] a, input [31:0] da);
        begin
            @(posedge ra_clk); ra_awaddr <= a; ra_awdata <= da; ra_awvalid <= 1'b1;
            @(posedge ra_clk);
            while (!ra_awready) @(posedge ra_clk);
            ra_awvalid <= 1'b0;
            repeat (6) @(posedge ra_clk);
        end
    endtask

    task reg_read(input [31:0] a, output [31:0] da);
        begin
            @(posedge ra_clk); ra_araddr <= a; ra_arvalid <= 1'b1;
            @(posedge ra_clk);
            while (!ra_arready) @(posedge ra_clk);
            ra_arvalid <= 1'b0;
            while (!ra_rvalid) @(posedge ra_clk);
            da = ra_rdata;
            repeat (4) @(posedge ra_clk);
        end
    endtask

    // ---- 主流程 ----
    integer i, j;
    reg [31:0] v, st;
    reg [31:0] tbl [0:28];
    integer n, k;
    reg [31:0] b0;

    initial begin
        for (i = 0; i < NPIX; i = i + 1) mem[i] = 8'd0;
        // 6x6 白块，中心 (20,20)
        for (i = 47; i < 53; i = i + 1)
            for (j = 47; j < 53; j = j + 1) mem[i*W + j] = 8'd255;
        // 4x4 白块，中心 (45,30)
        for (i = 118; i < 124; i = i + 1)
            for (j = 243; j < 249; j = j + 1) mem[i*W + j] = 8'd255;

        rst_n = 0; ra_rst_n = 0;
        repeat (20) @(posedge clk);
        rst_n = 1; ra_rst_n = 1;
        repeat (20) @(posedge clk);

        reg_read(32'h14, v);
        $display("[tb] VERSION = %08x %s", v, (v === 32'h00010000) ? "OK" : "BAD");

        reg_write(32'h04, 32'd0);      // FRAME_ADDR = 0
        reg_write(32'h08, 32'd0);      // RESULT_ADDR
        reg_write(32'h00, 32'd0);
        reg_write(32'h00, 32'd1);      // START

        st = 0;
        for (k = 0; k < 200000; k = k + 1) begin
            reg_read(32'h80, b0);
            if (b0[0]) begin st = b0; k = 999999; end
        end
        if (st[0]) begin
            reg_read(32'h0C, st);
            $display("[tb] STATUS = %08x  n_cand=%0d err=%0d", st, st[15:8], st[2]);
            n = st[15:8];
            for (k = 0; k < 28; k = k + 1) begin
                reg_write(32'h10, k);
                reg_read(32'h10, tbl[k]);
            end
            $display("[tb] n_cand=%0d", tbl[0] & 32'hff);
            for (k = 0; k < 4; k = k + 1) begin
                $display("     #%0d (%0d,%0d) area=%0d peak=%0d", k,
                    ((tbl[1+k*2] >> 16) & 32'hffff), (tbl[1+k*2] & 32'hffff),
                    ((tbl[2+k*2] >> 16) & 32'hffff), (tbl[2+k*2] & 32'hffff));
            end
            $display("VERDICT USER-OP-SMALL-%s", (tbl[0] & 32'hff) >= 1 ? "OK" : "FAIL");
        end else begin
            $display("VERDICT USER-OP-SMALL-FAIL (timeout)");
        end
        $finish;
    end

    initial begin
        #20_000_000;
        $display("VERDICT USER-OP-SMALL-FAIL (global timeout)");
        $finish;
    end
endmodule
