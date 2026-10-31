// tb_user_op_line.v —— 用「学长那种平台模型」验证行流适配层
// 平台：算子发 AR，平台 2 拍后回 512 位（64 字节），itf_rready 不参与
// 验证：检测器收到的前 256 字节 == 帧内存从 frame_base 起的连续字节
`timescale 1ns/1ps
module tb_user_op_line;

localparam W = 64, H = 48;
localparam NPIX = W*H;

reg clk = 0, ra_clk = 0;
always #2.5 clk = ~clk;        // 200 MHz
always #10  ra_clk = ~ra_clk;  //  50 MHz
reg rst_n = 0, ra_rst_n = 0;
reg [15:0] dbg_ar_n = 0;
reg [511:0] wrap = 512'd0;
integer kk;

// ---------------- 平台模型 ----------------
reg  [7:0]   bmem [0:262143];      // 字节寻址帧内存
reg  [511:0] rdata_r = 512'd0;
reg  [31:0]  ar_addr_l = 0;
reg          plat_rv    = 1'b0;
reg  [1:0]   rv_cnt     = 2'd0;
reg          plat_busy  = 1'b0;

wire [511:0] itf_rdata  = rdata_r;
wire         itf_rvalid = plat_rv;
wire         itf_arready = !plat_busy;

wire [31:0] itf_araddr;
wire        itf_arvalid;
wire        itf_rready;
wire [31:0] itf_awaddr;  wire [511:0] itf_awdata;  wire itf_awvalid;

// ---------------- 寄存器口 ----------------
reg  [31:0] ra_awaddr = 0, ra_awdata = 0;
reg         ra_awvalid = 0;
reg  [31:0] ra_araddr = 0;
reg         ra_arvalid = 0;
wire [31:0] ra_rdata;
wire        ra_rvalid;
wire        ra_awready, ra_arready;
wire [1:0]  led;

ip2_user_op #(.W(W), .H(H), .SE(5), .MAX_CAND(8)) dut (
    .itf_ra_awaddr(ra_awaddr), .itf_ra_awdata(ra_awdata), .itf_ra_awvalid(ra_awvalid),
    .itf_ra_awready(ra_awready),
    .itf_ra_araddr(ra_araddr), .itf_ra_arvalid(ra_arvalid), .itf_ra_arready(ra_arready),
    .itf_ra_rdata(ra_rdata),   .itf_ra_rvalid(ra_rvalid),   .itf_ra_rready(1'b1),
    .itf_awaddr(itf_awaddr),   .itf_awdata(itf_awdata),     .itf_awvalid(itf_awvalid),
    .itf_awready(1'b1),
    .itf_araddr(itf_araddr),   .itf_arvalid(itf_arvalid),   .itf_arready(itf_arready),
    .itf_rdata(itf_rdata),     .itf_rvalid(itf_rvalid),     .itf_rready(itf_rready),
    .led(led),
    .clk(clk), .ra_clk(ra_clk), .rst_n(rst_n), .ra_rst_n(ra_rst_n)
);

// 平台时序（v2）：接受最多 8 个 AR 排队，按序 2 拍后回 512 位数据
//   真平台就是这种“流水接受、顺序返回”的行为；旧模型只能挂 1 个 AR，会把流水掩盖成丢包
reg [31:0] pq [0:7];
reg [3:0]  pq_wp, pq_rp, pq_cnt;
reg        resp_pend;
reg [1:0]  rv_cnt2;
reg [5:0]  cool;   // 响应间隔（真平台 ~1024 clk/行，这里取 64 足够跨域）
assign itf_arready = (pq_cnt < 4'd8);

always @(posedge clk) begin
    if (!rst_n) begin
        pq_wp <= 4'd0; pq_rp <= 4'd0; pq_cnt <= 4'd0;
        plat_rv <= 1'b0; rv_cnt2 <= 2'd0; resp_pend <= 1'b0; cool <= 6'd0;
        ar_addr_l <= 32'd0; dbg_ar_n <= 0;
    end else begin
        plat_rv <= 1'b0;

        // 入队
        if (itf_arvalid && itf_arready) begin
            pq[pq_wp] <= itf_araddr;
            pq_wp     <= pq_wp + 4'd1;
            pq_cnt    <= pq_cnt + 4'd1;
            if (dbg_ar_n < 6) $display("  AR#%0d addr=%0d", dbg_ar_n, itf_araddr);
            dbg_ar_n  <= dbg_ar_n + 1;
        end

        // 出队响应
        if (cool != 6'd0) cool <= cool - 6'd1;
        if (!resp_pend && (pq_cnt != 4'd0) && (cool == 6'd0)) begin
            ar_addr_l <= pq[pq_rp];
            for (kk = 0; kk < 64; kk = kk + 1)
                wrap[kk*8 +: 8] <= bmem[pq[pq_rp] + kk];
            pq_rp     <= pq_rp + 4'd1;
            pq_cnt    <= pq_cnt - 4'd1;
            resp_pend <= 1'b1;
            rv_cnt2   <= 2'd2;
        end else if (resp_pend) begin
            if (rv_cnt2 != 2'd0) rv_cnt2 <= rv_cnt2 - 2'd1;
            else begin
                plat_rv   <= 1'b1;
                rdata_r   <= wrap;
                resp_pend <= 1'b0;
                cool      <= 6'd63;
            end
        end
    end
end

integer i, k, errs = 0;
reg [7:0] expect;

task reg_write(input [31:0] a, input [31:0] d);
begin
    @(posedge ra_clk); ra_awaddr <= a; ra_awdata <= d; ra_awvalid <= 1'b1;
    @(posedge ra_clk); while (!ra_awready) @(posedge ra_clk);
    ra_awvalid <= 1'b0;
end
endtask

initial begin
    for (i = 0; i < 262144; i = i + 1) bmem[i] = i[7:0];

    repeat (12) @(posedge ra_clk);
    rst_n = 1; ra_rst_n = 1;
    repeat (20) @(posedge ra_clk);

    reg_write(32'h04, 32'd0);   // FRAME_ADDR
    reg_write(32'h00, 32'd1);   // START
    $display("START 已写");

    for (i = 0; i < 1000000; i = i + 1) begin
        @(posedge ra_clk);
        if (dut.px_pushed >= NPIX) i = 1000000;
    end
    $display("PUSHED=%0d  请求行=%0d  AR=%0d  RV=%0d  WD=%0d",
             dut.px_pushed, dut.line_idx, dut.dbg_ar, dut.dbg_rv, dut.dbg_wd);

    for (i = 0; i < 256; i = i + 1) begin
        expect = i[7:0];
        if (dut.cap_mem[i] !== expect) begin
            if (errs < 6) $display("  MISMATCH cap[%0d]=%0d 期望 %0d", i, dut.cap_mem[i], expect);
            errs = errs + 1;
        end
    end
    $display("捕获比对：%0d / 256 不一致", errs);
    $display("VERDICT %s", (errs == 0) ? "LINE-OK" : "LINE-FAIL");
    $finish;
end

initial begin
    #3000000;
    $display("TB TIMEOUT pushed=%0d req=%0d ar=%0d", dut.px_pushed, dut.line_idx, dut.dbg_ar);
    $display("  feed_on=%b start_req=%b o_ext_go=%b lin_req_t=%b s_lin_req=%b req_pend=%b arv_q=%b ret_busy=%b lbusy=%b",
             dut.feed_on, dut.start_req, dut.o_ext_go, dut.lin_req_t, dut.s_lin_req,
             dut.req_pend, dut.plat_arvalid_q, dut.ret_busy, dut.lf_cnt);
    $display("  ext_ready=%b ext_cnt? fst=%0d", dut.o_ext_ready, dut.u_ip2.fst);
    $display("VERDICT TIME-FAIL");
    $finish;
end


    // ---- 进度探针（调试用）----
    integer pdiv = 0;
    always @(posedge clk) begin
        pdiv <= pdiv + 1;
        if (pdiv % 400 == 0)
            $display("  t=%0t px=%0d infl=%0d lfc=%0d line=%0d adq=%0d arv=%b",
                     $time, dut.px_pushed, dut.inflight, dut.lf_cnt, dut.line_idx,
                     dut.adq_cnt, dut.plat_arvalid_q, dut.u_ip2.fst);
    end
endmodule
