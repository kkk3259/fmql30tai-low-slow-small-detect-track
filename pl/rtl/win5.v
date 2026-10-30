// win5.v —— 流式 NxN 窗口（行缓存 + 流水线），输出 min（腐蚀）或 max（膨胀）
//
// 【2026-10-28】从固定 5x5 改成**参数化 SE（窗口边长，奇数）**，默认 21x21。
//   原因：Top-Hat = I - opening(I)，开运算会抹掉"比窗口小"的亮块，
//   所以 SE=5 只能检出 1~4 px 的目标（实测：2/3/4 px 检出，5 px 以上全丢）。
//   比赛目标 15~70 px，必须放大窗口：SE=21 可检 <=20 px。
//
// 【结构】
//   SE-1 条行缓存（每条 W 拍延迟，循环 RAM，深度 W+1）
//   → SE 个行抽头（每行 SE 深移位，共 SE*SE*8 个触发器）
//   → 行内 min/max（SE 输入链）→ 行间 min/max（SE 输入链）
//   延迟：DELAY = (SE/2)*W + (SE/2) + 1（对应窗口中心像素）
//   valid 用循环 RAM 延迟线（不能再用 DELAY 位移位寄存器：SE=21 时是 6411 位）
//
// 【边界】因果窗口：左/上边界回绕、右下边界缺失。检测不受影响（目标在内部，
//   且后续 CFAR 31x31 本身丢 15 像素边界）。
module win5 #(
    parameter W     = 32,
    parameter SE    = 5,      // 窗口边长（奇数）：默认 5（与历史版本逐像素一致，21 待验证）
    parameter IS_MAX = 0,     // 0 = min（腐蚀），1 = max（膨胀）
    parameter PAD   = 8'd255, // 边界填充值：腐蚀 255（min 中性）、膨胀 0（max 中性）
    parameter DLY   = 0       // 覆盖延迟（0 = 按公式自动算，仅调试/对齐用）
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] i_data,
    input  wire i_valid,
    output wire i_ready,
    output wire [7:0] o_data,
    output wire o_valid,
    input  wire o_ready
);
    localparam HALF  = SE / 2;
    localparam NR    = SE - 1;               // 行缓存条数
    localparam DEPTH = W + 1;                // 每条行缓存循环深度
    localparam PW    = (((DEPTH)<=2)?1:((DEPTH)<=4)?2:((DEPTH)<=8)?3:((DEPTH)<=16)?4:((DEPTH)<=32)?5:((DEPTH)<=64)?6:((DEPTH)<=128)?7:((DEPTH)<=256)?8:((DEPTH)<=512)?9:((DEPTH)<=1024)?10:((DEPTH)<=2048)?11:((DEPTH)<=4096)?12:((DEPTH)<=8192)?13:((DEPTH)<=16384)?14:((DEPTH)<=32768)?15:((DEPTH)<=65536)?16:((DEPTH)<=131072)?17:((DEPTH)<=262144)?18:((DEPTH)<=524288)?19:((DEPTH)<=1048576)?20:((DEPTH)<=2097152)?21:((DEPTH)<=4194304)?22:((DEPTH)<=8388608)?23:((DEPTH)<=16777216)?24:((DEPTH)<=33554432)?25:((DEPTH)<=67108864)?26:((DEPTH)<=134217728)?27:((DEPTH)<=268435456)?28:((DEPTH)<=536870912)?29:((DEPTH)<=1073741824)?30:((DEPTH)<=2147483648)?31:32);
    localparam DELAY = (DLY == 0) ? (HALF * W + HALF + 1) : DLY;  // 输入 → 窗口对齐延迟
    localparam VD    = DELAY + 1;            // valid 延迟线深度
    localparam VPW   = (((VD)<=2)?1:((VD)<=4)?2:((VD)<=8)?3:((VD)<=16)?4:((VD)<=32)?5:((VD)<=64)?6:((VD)<=128)?7:((VD)<=256)?8:((VD)<=512)?9:((VD)<=1024)?10:((VD)<=2048)?11:((VD)<=4096)?12:((VD)<=8192)?13:((VD)<=16384)?14:((VD)<=32768)?15:((VD)<=65536)?16:((VD)<=131072)?17:((VD)<=262144)?18:((VD)<=524288)?19:((VD)<=1048576)?20:((VD)<=2097152)?21:((VD)<=4194304)?22:((VD)<=8388608)?23:((VD)<=16777216)?24:((VD)<=33554432)?25:((VD)<=67108864)?26:((VD)<=134217728)?27:((VD)<=268435456)?28:((VD)<=536870912)?29:((VD)<=1073741824)?30:((VD)<=2147483648)?31:32);

    wire hs = i_valid && i_ready;
    assign i_ready = o_ready;

    // ---------------- 行缓存链：rdout[0]=当前行，rdout[k]=延迟 k*W ----------------
    wire [7:0] rdout [0:NR];
    assign rdout[0] = i_data;

    genvar gi;
    generate
        for (gi = 0; gi < NR; gi = gi + 1) begin : g_lb
            reg [7:0] mem [0:DEPTH-1];
            reg [PW-1:0] wp;
            reg [PW-1:0] fill;
            wire [PW-1:0] rp = (wp == DEPTH[PW-1:0] - 1'b1) ? {PW{1'b0}} : (wp + 1'b1);
            wire full = (fill >= W[PW-1:0]);

            assign rdout[gi+1] = full ? mem[rp] : PAD;

            // 独立 always 写块（标准 1写1读 RAM 写法）；
            // 同步复位：Vivado 拒绝"RAM 写 + 异步复位"的组合（[Synth 8-3391]）
            always @(posedge clk) begin
                if (!rst_n) begin
                    wp   <= {PW{1'b0}};
                    fill <= {PW{1'b0}};
                end else if (hs) begin
                    mem[wp] <= rdout[gi];
                    if (wp == DEPTH[PW-1:0] - 1'b1) wp <= {PW{1'b0}};
                    else                            wp <= wp + 1'b1;
                    if (fill < W[PW-1:0]) fill <= fill + 1'b1;
                end
            end
        end
    endgenerate

    // ---------------- 行抽头：SE 行 × 每行 SE 深 ----------------
    reg [7:0] tap [0:(SE*SE)-1];   // tap[r*SE + c]
    integer r, c;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (r = 0; r < SE; r = r + 1)
                for (c = 0; c < SE; c = c + 1)
                    tap[r*SE+c] <= PAD;
        end else if (hs) begin
            for (r = 0; r < SE; r = r + 1) begin
                for (c = SE-1; c > 0; c = c - 1)
                    tap[r*SE+c] <= tap[r*SE+c-1];
                tap[r*SE] <= rdout[r];
            end
        end
    end

    // ---------------- 归约：行内 → 行间（平衡树，不是线性链）----------------
    // 注意：不能用 always @(*) + for 循环读数组 —— iverilog 对"数组/循环依赖"的
    // 敏感表推导不可靠（实测会导致 41% 像素错位），这里全部用实例化的树形归约实现。
    // 早期版本用线性链 hc[i]=min(hc[i-1],tap[i])：21×21 时深度 441 级比较，
    // 综合后 60 级逻辑、WNS -7.775 ns @50 MHz → 改为每行一棵树、行结果再一棵树。
    wire [7:0] rowmin [0:SE-1];     // 每行的行内最小值/最大值

    // tap 是 unpacked 数组，树模块要扁平向量，这里重新拼一份
    wire [SE*SE*8-1:0] tap_flat;
    genvar gt;
    generate
        for (gt = 0; gt < SE*SE; gt = gt + 1) begin : g_tapflat
            assign tap_flat[gt*8 +: 8] = tap[gt];
        end
    endgenerate

    genvar gr;
    generate
        for (gr = 0; gr < SE; gr = gr + 1) begin : g_rowtree
            minmax_tree #(.N(SE), .W(8), .IS_MAX(IS_MAX)) u_row (
                .din  (tap_flat[gr*SE*8 +: SE*8]),
                .dout (rowmin[gr])
            );
        end
    endgenerate

    // 行结果再归约成一棵树
    wire [SE*8-1:0] rowflat;
    generate
        for (gr = 0; gr < SE; gr = gr + 1) begin : g_rowflat
            assign rowflat[gr*8 +: 8] = rowmin[gr];
        end
    endgenerate

    wire [7:0] vred;
    minmax_tree #(.N(SE), .W(8), .IS_MAX(IS_MAX)) u_col (
        .din  (rowflat),
        .dout (vred)
    );

    // ---------------- valid 延迟线（循环 RAM，1 bit）----------------
    reg vmem [0:VD-1];
    reg [VPW-1:0] vwp;
    reg [VPW-1:0] vfill;
    wire [VPW-1:0] vrp = (vwp == VD[VPW-1:0] - 1'b1) ? {VPW{1'b0}} : (vwp + 1'b1);
    wire vfull = (vfill >= DELAY[VPW-1:0]);
    wire vdelayed = vfull ? vmem[vrp] : 1'b0;

    always @(posedge clk) begin
        if (!rst_n) begin
            vwp   <= {VPW{1'b0}};
            vfill <= {VPW{1'b0}};
        end else if (o_ready) begin
            // 注意：这一级必须按 o_ready 自由移位（不是 hs），否则输入停了以后
            // 指针冻结、valid 排不空（实测尾巴多 5 拍，与新老版本对不上）
            vmem[vwp] <= i_valid;
            if (vwp == VD[VPW-1:0] - 1'b1) vwp <= {VPW{1'b0}};
            else                           vwp <= vwp + 1'b1;
            if (vfill < DELAY[VPW-1:0]) vfill <= vfill + 1'b1;
        end
    end

    reg [7:0] o_data_r;
    reg o_valid_r;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin o_data_r <= 8'd0; o_valid_r <= 1'b0; end
        else if (o_ready) begin
            o_data_r  <= vred;
            o_valid_r <= vdelayed;
        end
    end
    assign o_data  = o_data_r;
    assign o_valid = o_valid_r;
endmodule
