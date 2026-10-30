// ip2_pix_fifo.v —— 像素流缓冲 FIFO（8 bit 宽，深度可配，块 RAM 版）
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
// 2026-10-26 改成块 RAM 版（Vivado 综合被迫）：
//   原实现是异步读（rd_data = mem[rptr] 组合输出）。Procise/Verific 会把它
//   映射成 DMEM（查找表 RAM），640×360 只需 6,672 个 LUT 当量；但 Vivado 把
//   262144×8 = 2 Mbit 铺成 32,768 个 RAMD64E（分布式 RAM），实测
//   "LUT as Memory 57,339 / 26,600 = 215%"、"Slice LUTs 116,341 = 148%"，
//   整个 IP 在 Vivado 里装不下。
//
//   改法：存储搬进块 RAM（2 Mbit ≈ 64 个 RAMB36，占本器件 265 块的 24%，
//   而我们块 RAM 用量原本是 0），对外端口语义完全不变（show-ahead）：
//   块 RAM 同步读出一拍才有效，所以用「预取 + 输出寄存器」实现 FWFT：
//     计数 count = 内存里的元素个数（不含输出寄存器里那个）
//     预取条件 fetch = (count != 0) && (!dout_v || take)
//     连续消费时可保持每拍 1 像素的吞吐（读延迟被预取隐藏）
//   片内块 RAM 容量 = DEPTH + 1（多一个输出寄存器）。
//
// 语义：标准同步 FIFO（读侧 show-ahead：rd_valid 为高时 rd_data 就是队首，
//       本拍 rd_ready 为高即消费掉）。
module ip2_pix_fifo #(
    parameter DEPTH = 512,                  // 必须是 2 的幂
    parameter AW    = 9                     // (((DEPTH)<=2)?1:((DEPTH)<=4)?2:((DEPTH)<=8)?3:((DEPTH)<=16)?4:((DEPTH)<=32)?5:((DEPTH)<=64)?6:((DEPTH)<=128)?7:((DEPTH)<=256)?8:((DEPTH)<=512)?9:((DEPTH)<=1024)?10:((DEPTH)<=2048)?11:((DEPTH)<=4096)?12:((DEPTH)<=8192)?13:((DEPTH)<=16384)?14:((DEPTH)<=32768)?15:((DEPTH)<=65536)?16:((DEPTH)<=131072)?17:((DEPTH)<=262144)?18:((DEPTH)<=524288)?19:((DEPTH)<=1048576)?20:((DEPTH)<=2097152)?21:((DEPTH)<=4194304)?22:((DEPTH)<=8388608)?23:((DEPTH)<=16777216)?24:((DEPTH)<=33554432)?25:((DEPTH)<=67108864)?26:((DEPTH)<=134217728)?27:((DEPTH)<=268435456)?28:((DEPTH)<=536870912)?29:((DEPTH)<=1073741824)?30:((DEPTH)<=2147483648)?31:32)
)(
    input  wire        clk,
    input  wire        rst_n,
    // 【2026-10-28】同步清空：每帧起始（F_RST）拉高一拍。
    // 为什么必须有：实测每帧结束 FIFO 里固定残留 120 字节（上一帧尾部），
    // 下一帧装帧时这 120 字节留在队头 → 整帧像素流平移 120 个像素
    // （候选坐标 x 全部 +120、最后 120 个像素永远读不到），且每帧都重复。
    input  wire        clr,

    // 写侧（来自 AXI 读主机）
    input  wire        wr_en,
    input  wire [7:0]  wr_data,
    output wire        wr_full,

    // 读侧（送给 IP2 链路）
    output wire [7:0]  rd_data,
    output wire        rd_valid,
    input  wire        rd_ready,           // 链路 i_ready

    // 水位（元素个数，含输出寄存器里那个）
    output wire [AW:0] level
);
    reg  [7:0]   mem [0:DEPTH-1];
    reg  [7:0]   dout;                      // 输出寄存器（FWFT）
    reg          dout_v;                    // 输出寄存器里有有效像素
    reg  [AW-1:0] wptr, rptr;               // 写/读地址（自然回绕）
    reg  [AW:0]  count;                     // 内存中的元素个数（不含 dout）

    wire full  = (count == DEPTH[AW:0]);    // 内存满
    wire take  = dout_v && rd_ready;        // 消费者取走队首
    wire fetch = (count != 0) && (!dout_v || take) && !clr;  // 从内存预取
    wire do_wr = wr_en && !full && !clr;

    assign wr_full  = full;
    assign rd_valid = dout_v;
    assign rd_data  = dout;
    assign level    = count + { {(AW){1'b0}}, dout_v };

    // ------------------------------------------------------------------
    // 写数据（独立块、无复位 —— Vivado/Verific 推断块 RAM 的必要写法）
    // ------------------------------------------------------------------
    always @(posedge clk) begin
        if (do_wr) mem[wptr] <= wr_data;
    end

    // ------------------------------------------------------------------
    // 块 RAM 读（独立块、无复位、同步读 → 数据在下一拍出现在 dout）
    // ------------------------------------------------------------------
    always @(posedge clk) begin
        if (fetch) dout <= mem[rptr];
    end

    // ------------------------------------------------------------------
    // 指针 / 计数 / 输出有效
    //
    // 注意：这里用【同步复位】（不是 negedge rst_n 异步复位）。
    // 原因：rptr / wptr 是块 RAM 的地址输入，Vivado 的 DRC REQP-1839
    // （RAMB36 async control check）会警告「驱动 RAMB 地址的寄存器带异步
    // 复位 → 复位期间可能破坏存储内容/读出值，且静态时序不分析这条路径」。
    // 改成同步复位后，RAMB 的地址寄存器和复位同时钟域，DRC 干净。
    // ------------------------------------------------------------------
    always @(posedge clk) begin
        if (!rst_n) begin
            wptr   <= {AW{1'b0}};
            rptr   <= {AW{1'b0}};
            count  <= {(AW+1){1'b0}};
            dout_v <= 1'b0;
        end else if (clr) begin
            wptr   <= {AW{1'b0}};
            rptr   <= {AW{1'b0}};
            count  <= {(AW+1){1'b0}};
            dout_v <= 1'b0;
        end else begin
            if (do_wr) wptr <= wptr + 1'b1;
            if (fetch) rptr <= rptr + 1'b1;

            if (take)  dout_v <= 1'b0;      // 先清
            if (fetch) dout_v <= 1'b1;      // 后置（同拍 take+fetch 时要保持为 1）

            case ({do_wr, fetch})
                2'b10:   count <= count + 1'b1;
                2'b01:   count <= count - 1'b1;
                default: ;                  // 00 不变；11 一进一出也不变
            endcase
        end
    end
endmodule
