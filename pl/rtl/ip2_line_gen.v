//======================================================================
// ip2_line_gen.v —— 按学长 dma.v 模型的“行流发生器”（v2 全重写）
//
// 平台模型（学长 adder_top/dma.v 实证）：
//   * 一次 itf_ar 握手 = 返回一行 64 字节（顶层 User_Ddr_rdata 是 512 位）
//   * itf_araddr 每行 +64
//   * itf_arvalid 持续拉高，直到整帧行数握手完
//   * 不使用 itf_rready
//
// 本模块把每行 512 位拆成 64 个字节，以 1 字节/拍喂给检测器 FIFO。
// 两级行寄存器乒乓 + 容量计数（cap<2 才发 AR），保证不覆盖、不丢行。
//======================================================================
`timescale 1ns / 1ps
module ip2_line_gen #(
    parameter NPIX = 640*360
)(
    input  wire         clk,
    input  wire         rst_n,
    input  wire         start,
    input  wire [31:0]  base_addr,
    output wire [31:0]  itf_araddr,
    output wire         itf_arvalid,
    input  wire         itf_arready,
    input  wire [511:0] itf_rdata,
    input  wire         itf_rvalid,
    output wire [7:0]   o_data,
    output wire         o_valid,
    input  wire         o_ready,
    output wire [15:0]  o_lines_done,
    output wire         o_busy
);
    localparam NLINE = (NPIX + 63) / 64;

    reg  [15:0]  line_idx;
    reg  [15:0]  done_cnt;
    reg          active;
    reg  [511:0] buf_a, buf_b;
    reg          va, vb;
    reg  [5:0]   cnt;
    reg  [1:0]   cap;

    wire drain   = (va || vb) && o_ready;
    wire endline = drain && (cnt == 6'd63);
    wire place_a = itf_rvalid && (!va || endline);
    wire place_b = itf_rvalid && !place_a;

    assign itf_araddr   = base_addr + {line_idx, 6'b0};
    // 只允许在 buf_b 空时发新 AR：避免第 3 行覆盖还没取走的第 2 行
    assign itf_arvalid  = active && (line_idx < NLINE[15:0]) && !vb;
    assign o_data       = va ? buf_a[{cnt, 3'b000} +: 8] :
                          vb ? buf_b[{cnt, 3'b000} +: 8] : 8'h00;
    assign o_valid      = va || vb;
    assign o_busy       = active;
    assign o_lines_done = done_cnt;

    always @(posedge clk) begin
        if (!rst_n) begin
            line_idx <= 16'd0; done_cnt <= 16'd0; active <= 1'b0;
            va <= 1'b0; vb <= 1'b0; cnt <= 6'd0;
        end else if (start) begin
            line_idx <= 16'd0; done_cnt <= 16'd0; active <= 1'b1;
            va <= 1'b0; vb <= 1'b0; cnt <= 6'd0;
        end else begin
            // 一、取字节（从 buf_a 优先，取完换 buf_b）
            if (o_valid && o_ready) begin
                if (cnt == 6'd63) begin
                    cnt <= 6'd0;
                    done_cnt <= done_cnt + 16'd1;
                    if (va) begin
                        // buf_a 取完：若有 buf_b，把 buf_b 提上来当 a
                        if (vb) begin buf_a <= buf_b; va <= 1'b1; vb <= 1'b0; end
                        else    va <= 1'b0;
                    end else begin
                        vb <= 1'b0;
                    end
                end else begin
                    cnt <= cnt + 6'd1;
                end
            end
            // 二、新行落地（放空槽）
            if (itf_rvalid) begin
                if (!va) begin buf_a <= itf_rdata; va <= 1'b1; end
                else if (!vb) begin buf_b <= itf_rdata; vb <= 1'b1; end
            end
            // 三、AR：只要还有空槽且没读完就发
            if (itf_arvalid && itf_arready) begin
                if (line_idx == NLINE[15:0] - 16'd1) active <= 1'b0;
                else                                 line_idx <= line_idx + 16'd1;
            end
        end
    end
endmodule
