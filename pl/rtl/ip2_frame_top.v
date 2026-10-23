// ============================================================================
// ip2_frame_top.v —— 帧级顶层：自测图案 -> IP2 全链 -> 候选统计 -> LED
//
// 由于 CFAR / CCL 都是"单帧一次"的状态机（CFAR 到 S_DONE 不再回 S_RUN，
// CCL 到 S_DONE 也不再回 S_RUN），所以帧与帧之间必须整链复位：
//     F_FEED（喂一帧） -> F_WAIT（等 CCL 吐完 36 字节） -> F_RST（整链复位 32 拍）
//     -> F_FEED ...
//
// 注意：CFAR 内部虚拟光栅是 (W+30)x(H+30)，它只在图像列上拉高 i_ready，
//       所以图案发生器必须按 ready/valid 握手推进（本模块已按此实现）。
//
// LED 指示：
//   led[0]   = 心跳：每 128 帧翻转一次（640x360 @100MHz 约 2.6ms/帧 -> 0.67s 周期）
//   led[3:1] = 本帧检出的候选个数（饱和到 7）
// ============================================================================
module ip2_frame_top #(
    parameter W = 640,
    parameter H = 360,
    parameter MAX_CAND = 5
)(
    input  wire       clk,
    input  wire       rst_n,      // 低有效
    output wire [3:0] led
);
    localparam F_FEED = 2'd0;
    localparam F_WAIT = 2'd1;
    localparam F_RST  = 2'd2;

    // ---------------------------------------------------------------
    // 内部上电复位：rst_n 释放后再同步 32 拍才让链路出复位
    // ---------------------------------------------------------------
    reg [4:0] rstc = 5'd0;
    reg       rst_ok = 1'b0;

    always @(posedge clk) begin
        if (!rst_n) begin
            rstc   <= 5'd0;
            rst_ok <= 1'b0;
        end else if (rstc != 5'h1f) begin
            rstc   <= rstc + 5'd1;
            rst_ok <= 1'b0;
        end else begin
            rst_ok <= 1'b1;
        end
    end

    // ---------------------------------------------------------------
    // 帧状态机
    // ---------------------------------------------------------------
    reg [1:0]  fst   = F_FEED;
    reg [5:0]  rcnt  = 6'd0;
    reg [5:0]  ocount = 6'd0;
    reg [7:0]  ncand  = 8'd0;
    reg [11:0] fcnt   = 12'd0;

    wire chain_rst_n = rst_ok && (fst != F_RST);

    // ---------------------------------------------------------------
    // 图案发生器 + IP2 全链
    // ---------------------------------------------------------------
    wire [7:0] pg_data;
    wire       pg_valid;
    wire       pg_done;
    wire       ch_ready;

    wire [7:0] ccl_data;
    wire       ccl_valid;

    ip2_pattern_gen #(.W(W), .H(H)) u_pat (
        .clk       (clk),
        .rst_n     (chain_rst_n),
        .en        ((fst == F_FEED) && rst_ok),
        .i_ready   (ch_ready),
        .o_data    (pg_data),
        .o_valid   (pg_valid),
        .frame_done(pg_done)
    );

    ip2_top_stream #(.W(W), .H(H), .MAX_CAND(MAX_CAND)) u_chain (
        .clk    (clk),
        .rst_n  (chain_rst_n),
        .i_data (pg_data),
        .i_valid(pg_valid),
        .i_ready(ch_ready),
        .o_data (ccl_data),
        .o_valid(ccl_valid),
        .o_ready(1'b1)
    );

    // ---------------------------------------------------------------
    // 收集 CCL 输出：共 1 + MAX_CAND*7 = 36 字节，第 0 字节是候选个数
    //   ocount 属于"帧内"计数 -> 跟链路一起复位
    //   ncand  属于"跨帧保持"    -> 只在 rst_n 复位（否则 LED 只在 F_RST 前后闪）
    // ---------------------------------------------------------------
    always @(posedge clk) begin
        if (!chain_rst_n) begin
            ocount <= 6'd0;
        end else if (ccl_valid && (ocount < 6'd36)) begin
            ocount <= ocount + 6'd1;
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            ncand <= 8'd0;
        end else if (ccl_valid && (ocount == 6'd0)) begin
            ncand <= ccl_data;
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            fst  <= F_FEED;
            rcnt <= 6'd0;
            fcnt <= 12'd0;
        end else begin
            case (fst)
                F_FEED: begin
                    if (pg_done) fst <= F_WAIT;
                end
                F_WAIT: begin
                    if (ocount == 6'd36) begin
                        fst  <= F_RST;
                        rcnt <= 6'd0;
                    end
                end
                F_RST: begin
                    if (rcnt == 6'd31) begin
                        fst  <= F_FEED;
                        rcnt <= 6'd0;
                        fcnt <= fcnt + 12'd1;
                    end else begin
                        rcnt <= rcnt + 6'd1;
                    end
                end
                default: fst <= F_FEED;
            endcase
        end
    end

    // ---------------------------------------------------------------
    // LED 指示
    // ---------------------------------------------------------------
    assign led[0]   = fcnt[7];
    assign led[3:1] = (ncand > 8'd7) ? 3'd7 : ncand[2:0];

endmodule
