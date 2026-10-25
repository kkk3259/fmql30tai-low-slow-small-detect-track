// ip2_pix_fifo.v —— 像素流缓冲 FIFO（8 bit 宽，深度可配）
//
// 为什么需要它：
//   IP2 链路（win5/tophat/cfar）是【连续像素流】假设的 —— 5×5 / 31×31 窗口
//   在几何上必须是相邻像素，一旦上游出现 valid 空拍（AXI 读主机在 burst
//   边界、或 CFAR 在 PAD 列反压之后重新取数时的几拍间隙），空洞会直接破坏
//   窗口几何，表现为「喂进去的像素一颗不差，但候选表全错」。
//   实测：tb_axi_top 里像素流 9216/9216 完全正确，但候选表 8/36 字节不对。
//
//  解决：读主机 → 本 FIFO → IP2 链路。FIFO 把 burst 间隙吸收掉，
//   只要 FIFO 不排空，链路看到的就是连续 valid。
//
// 语义：标准同步 FIFO（读侧 show-ahead：o_valid=!empty，o_data 为队首）。
module ip2_pix_fifo #(
    parameter DEPTH = 512,                  // 必须是 2 的幂
    parameter AW    = 9                     // $clog2(DEPTH)
)(
    input  wire        clk,
    input  wire        rst_n,

    // 写侧（来自 AXI 读主机）
    input  wire        wr_en,
    input  wire [7:0]  wr_data,
    output wire        wr_full,

    // 读侧（送给 IP2 链路）
    output wire [7:0]  rd_data,
    output wire        rd_valid,
    input  wire        rd_ready,           // 链路 i_ready

    // 水位（元素个数）
    output wire [AW:0] level
);
    reg [7:0] mem [0:DEPTH-1];
    reg [AW:0] wptr, rptr;                 // 多 1 bit 区分空/满

    wire [AW:0] wptr_n = wptr + 1'b1;
    wire [AW:0] rptr_n = rptr + 1'b1;

    wire empty = (wptr == rptr);
    wire full  = (wptr[AW] != rptr[AW]) && (wptr[AW-1:0] == rptr[AW-1:0]);

    assign wr_full  = full;
    assign rd_valid = !empty;
    assign rd_data  = mem[rptr[AW-1:0]];
    assign level    = wptr - rptr;

    wire do_wr = wr_en && !full;
    wire do_rd = rd_valid && rd_ready;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wptr <= {(AW+1){1'b0}};
        end else if (do_wr) begin
            wptr <= wptr_n;
        end
    end

    // 写数据（独立块，标准 RAM 写法；同址读写由 FIFO 指针保证不发生）
    always @(posedge clk) begin
        if (do_wr) mem[wptr[AW-1:0]] <= wr_data;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rptr <= {(AW+1){1'b0}};
        end else if (do_rd) begin
            rptr <= rptr_n;
        end
    end
endmodule
