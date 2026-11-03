// cfar_threshold_stream.v —— 流式 CFAR 自适应阈值（单趟、真实标准差）
// 判决：thr = mean + K×std + FLOOR，img > thr 判目标(255)。
//
// 【为什么从 MAD 改成 std（2026-10-23）】
//   PS 侧基线 detect_v1.py 用的是真实标准差：
//       mu  = boxFilter(img,  (31,31))
//       mu2 = boxFilter(img², (31,31))
//       sd  = sqrt(mu2 - mu²)
//       thr = mu + k·sd + floor,  k = 4.0,  floor = 3.0
//   早期硬件用 MAD 近似（thr = mean + 5·MAD + 3），与 Python 差一个 1.4826 常数，
//   候选表永远对不上 → 现按真实 std 重写。
//
// 【不开方器的等价判决（关键，改这里前先看懂）】
//   记 A = 裁剪后窗口面积、S1 = Σx、S2 = Σx²：
//       mu = S1/A,   sd = sqrt(A·S2 - S1²)/A
//       x > mu + k·sd + floor
//     ⟺  L > k·sqrt(A·S2 - S1²),       其中 L = x·A - S1 - floor·A
//     ⟺  (L > 0) 且 L² > k²·(A·S2 - S1²)     ← 两边都非负才能平方
//   位宽：L ≤ 255×961 = 245,055（18 bit）；L² ≤ 6.01e10（36 bit）；
//        A·S2 - S1² ≤ 961×62,489,025 ≈ 6.01e10（36 bit）；×k²=16 ≤ 9.6e11（40 bit）。
//   所以硬件上只需要 4 个真乘法器（8×8 平方、8×11、11×26、18×18），
//   不需要除法/开方；k²=16 与 WMAX 都是 2 的幂，综合成移位。
//
// 【因果对齐（单趟，两个盒共用同一个窗口）】
//   虚拟光栅 W15×H15：图像占 row<H、col<W，其余位置是 PAD（补 0）。
//     - 盒1 输入 cur_px、盒2 输入 cur_px²，共用同一套列和与环形延迟线，
//       因此同一拍得到的 S1、S2 描述的是**同一个** 31×31 窗口；
//     - 虚拟位置 t 的窗口 = 行 [r-30,r] × 列 [c-30,c]，中心 u = (r-15, c-15)；
//     - 中心像素 x(u) 由 rb2 取回（延迟 CENTER_OFF = 15 行 + 15 列 = 15·W15+15）；
//     - 窗口面积 A 按 u 裁剪：crow = row-15、ccol = col-15，
//       与 PS 侧 max/min 裁剪完全一致（上/下/左/右都对齐，无 1 列偏移）。
//   输出行 row∈[15,H+15)、列 col∈[15,W+15) 恰好 N=H×W 个；之后 state→S_DONE。
//
// 【存储（640×360 → W15=655, H15=375, DLY=20,305, CENTER_OFF=9,840）】
//     rb1 20,306×8（延迟 DLY，供两个盒的移出值）
//     rb2  9,841×8（延迟 CENTER_OFF，供中心像素 x(u)）
//     cs1   655×13、cs2 655×21
//   合计 ≈ 241 Kbit（原两趟全帧方案 7.5 Mbit，折合 16 万 LUT，装不进器件）。
//
// 【2026-10-23 布局失败后减负】原设计还有 rb3 = 20,306×16（平方流延迟线），
//   但 (x(t-DLY))² 恒等于 x²(t-DLY)，另存一条 16 bit 平方流是冗余的 →
//   删 rb3，读出 rb1 后现算平方。LUTRAM 799 Kbit → 474 Kbit（−41%），仿真逐位一致。
//   背景：640×360 版 Place 报 PLACE-0021 "place error: Global Placement failed"
//   （legalize 阶段 network simplex infeasible），根因是 LUTRAM 占用过高压满 SLICEM 列。
//
// 【RAM 写法约束（Verific）】写必须在独立 always 块里、不能写进状态机 case 分支，
//   否则报 ELAB-E-353 "Failed to dissolve the memory into bits ... too large"。
//   环形线统一“写 wp、读 (wp+1) mod DEPTH” → 延迟 = DEPTH-1，全数组都是 1 写 1 读。
module cfar_threshold_stream #(
    parameter W = 64,
    parameter H = 64,
    parameter WIN = 31,
    // 门限：thr = mean + K*sd + FLOOR
    // K=4（比赛早期的保守值）在 31×31 窗口里会把“比结构元小的亮块”自己抑制掉：
    //   10px 亮块 → mean≈24 σ≈59 → thr≈262 > 亮块值 232，直接漏检。
    // 实测（2026-10-29）改成 K=1 后 2~20px 都能出来，见 docs/13 §14。
    parameter K = 1,
    parameter FLOOR = 3,
    // 1 = rb1/rb2 用同步读（推断成 BRAM，省约 10,000 LUTRAM）
    // 0 = 原组合读（推断成 LUTRAM）
    parameter USE_BRAM = 0
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] i_data,
    input  wire i_valid,
    output wire i_ready,
    output wire [7:0] o_data,   // 二值图（255/0）
    output wire [7:0] o_enh,    // 对齐的增强图（中心像素，与 o_data 同位置）
    output wire o_valid,
    input  wire o_ready
);
    localparam N     = W * H;
    localparam [5:0] WIN_V = WIN;   // Procise: parameter 不能位选
    localparam HALF  = WIN / 2;                     // 15
    localparam W15   = W + HALF;                    // 虚拟列宽
    localparam H15   = H + HALF;                    // 虚拟行高
    localparam N_EXT = H15 * W15;                   // 虚拟总位置数
    localparam DLY   = WIN * W15;                   // 盒竖直延迟：31 行
    localparam DEP_A = DLY + 1;                     // 读 (wp+1) → 延迟 DLY
    localparam CENTER_OFF = HALF * W15 + HALF;      // 15 行 + 15 列
    localparam DEP_B = CENTER_OFF + 1;              // 读 (wp+1) → 延迟 CENTER_OFF

    localparam CNT_W = (((N_EXT + 1)<=2)?1:((N_EXT + 1)<=4)?2:((N_EXT + 1)<=8)?3:((N_EXT + 1)<=16)?4:((N_EXT + 1)<=32)?5:((N_EXT + 1)<=64)?6:((N_EXT + 1)<=128)?7:((N_EXT + 1)<=256)?8:((N_EXT + 1)<=512)?9:((N_EXT + 1)<=1024)?10:((N_EXT + 1)<=2048)?11:((N_EXT + 1)<=4096)?12:((N_EXT + 1)<=8192)?13:((N_EXT + 1)<=16384)?14:((N_EXT + 1)<=32768)?15:((N_EXT + 1)<=65536)?16:((N_EXT + 1)<=131072)?17:((N_EXT + 1)<=262144)?18:((N_EXT + 1)<=524288)?19:((N_EXT + 1)<=1048576)?20:((N_EXT + 1)<=2097152)?21:((N_EXT + 1)<=4194304)?22:((N_EXT + 1)<=8388608)?23:((N_EXT + 1)<=16777216)?24:((N_EXT + 1)<=33554432)?25:((N_EXT + 1)<=67108864)?26:((N_EXT + 1)<=134217728)?27:((N_EXT + 1)<=268435456)?28:((N_EXT + 1)<=536870912)?29:((N_EXT + 1)<=1073741824)?30:((N_EXT + 1)<=2147483648)?31:32);
    localparam CW    = (((W15 + 1)<=2)?1:((W15 + 1)<=4)?2:((W15 + 1)<=8)?3:((W15 + 1)<=16)?4:((W15 + 1)<=32)?5:((W15 + 1)<=64)?6:((W15 + 1)<=128)?7:((W15 + 1)<=256)?8:((W15 + 1)<=512)?9:((W15 + 1)<=1024)?10:((W15 + 1)<=2048)?11:((W15 + 1)<=4096)?12:((W15 + 1)<=8192)?13:((W15 + 1)<=16384)?14:((W15 + 1)<=32768)?15:((W15 + 1)<=65536)?16:((W15 + 1)<=131072)?17:((W15 + 1)<=262144)?18:((W15 + 1)<=524288)?19:((W15 + 1)<=1048576)?20:((W15 + 1)<=2097152)?21:((W15 + 1)<=4194304)?22:((W15 + 1)<=8388608)?23:((W15 + 1)<=16777216)?24:((W15 + 1)<=33554432)?25:((W15 + 1)<=67108864)?26:((W15 + 1)<=134217728)?27:((W15 + 1)<=268435456)?28:((W15 + 1)<=536870912)?29:((W15 + 1)<=1073741824)?30:((W15 + 1)<=2147483648)?31:32);
    localparam CH    = (((H15 + 1)<=2)?1:((H15 + 1)<=4)?2:((H15 + 1)<=8)?3:((H15 + 1)<=16)?4:((H15 + 1)<=32)?5:((H15 + 1)<=64)?6:((H15 + 1)<=128)?7:((H15 + 1)<=256)?8:((H15 + 1)<=512)?9:((H15 + 1)<=1024)?10:((H15 + 1)<=2048)?11:((H15 + 1)<=4096)?12:((H15 + 1)<=8192)?13:((H15 + 1)<=16384)?14:((H15 + 1)<=32768)?15:((H15 + 1)<=65536)?16:((H15 + 1)<=131072)?17:((H15 + 1)<=262144)?18:((H15 + 1)<=524288)?19:((H15 + 1)<=1048576)?20:((H15 + 1)<=2097152)?21:((H15 + 1)<=4194304)?22:((H15 + 1)<=8388608)?23:((H15 + 1)<=16777216)?24:((H15 + 1)<=33554432)?25:((H15 + 1)<=67108864)?26:((H15 + 1)<=134217728)?27:((H15 + 1)<=268435456)?28:((H15 + 1)<=536870912)?29:((H15 + 1)<=1073741824)?30:((H15 + 1)<=2147483648)?31:32);
    localparam PA    = (((DEP_A)<=2)?1:((DEP_A)<=4)?2:((DEP_A)<=8)?3:((DEP_A)<=16)?4:((DEP_A)<=32)?5:((DEP_A)<=64)?6:((DEP_A)<=128)?7:((DEP_A)<=256)?8:((DEP_A)<=512)?9:((DEP_A)<=1024)?10:((DEP_A)<=2048)?11:((DEP_A)<=4096)?12:((DEP_A)<=8192)?13:((DEP_A)<=16384)?14:((DEP_A)<=32768)?15:((DEP_A)<=65536)?16:((DEP_A)<=131072)?17:((DEP_A)<=262144)?18:((DEP_A)<=524288)?19:((DEP_A)<=1048576)?20:((DEP_A)<=2097152)?21:((DEP_A)<=4194304)?22:((DEP_A)<=8388608)?23:((DEP_A)<=16777216)?24:((DEP_A)<=33554432)?25:((DEP_A)<=67108864)?26:((DEP_A)<=134217728)?27:((DEP_A)<=268435456)?28:((DEP_A)<=536870912)?29:((DEP_A)<=1073741824)?30:((DEP_A)<=2147483648)?31:32);               // rb1/rb3 指针位宽
    localparam PB    = (((DEP_B)<=2)?1:((DEP_B)<=4)?2:((DEP_B)<=8)?3:((DEP_B)<=16)?4:((DEP_B)<=32)?5:((DEP_B)<=64)?6:((DEP_B)<=128)?7:((DEP_B)<=256)?8:((DEP_B)<=512)?9:((DEP_B)<=1024)?10:((DEP_B)<=2048)?11:((DEP_B)<=4096)?12:((DEP_B)<=8192)?13:((DEP_B)<=16384)?14:((DEP_B)<=32768)?15:((DEP_B)<=65536)?16:((DEP_B)<=131072)?17:((DEP_B)<=262144)?18:((DEP_B)<=524288)?19:((DEP_B)<=1048576)?20:((DEP_B)<=2097152)?21:((DEP_B)<=4194304)?22:((DEP_B)<=8388608)?23:((DEP_B)<=16777216)?24:((DEP_B)<=33554432)?25:((DEP_B)<=67108864)?26:((DEP_B)<=134217728)?27:((DEP_B)<=268435456)?28:((DEP_B)<=536870912)?29:((DEP_B)<=1073741824)?30:((DEP_B)<=2147483648)?31:32);               // rb2 指针位宽

    localparam A_W   = 11;                          // 面积 ≤ 961
    localparam CS1_W = (((WIN * 255)<=2)?1:((WIN * 255)<=4)?2:((WIN * 255)<=8)?3:((WIN * 255)<=16)?4:((WIN * 255)<=32)?5:((WIN * 255)<=64)?6:((WIN * 255)<=128)?7:((WIN * 255)<=256)?8:((WIN * 255)<=512)?9:((WIN * 255)<=1024)?10:((WIN * 255)<=2048)?11:((WIN * 255)<=4096)?12:((WIN * 255)<=8192)?13:((WIN * 255)<=16384)?14:((WIN * 255)<=32768)?15:((WIN * 255)<=65536)?16:((WIN * 255)<=131072)?17:((WIN * 255)<=262144)?18:((WIN * 255)<=524288)?19:((WIN * 255)<=1048576)?20:((WIN * 255)<=2097152)?21:((WIN * 255)<=4194304)?22:((WIN * 255)<=8388608)?23:((WIN * 255)<=16777216)?24:((WIN * 255)<=33554432)?25:((WIN * 255)<=67108864)?26:((WIN * 255)<=134217728)?27:((WIN * 255)<=268435456)?28:((WIN * 255)<=536870912)?29:((WIN * 255)<=1073741824)?30:((WIN * 255)<=2147483648)?31:32) + 1;               // 13  列和（灰阶）
    localparam WS1_W = (((WIN * WIN * 255)<=2)?1:((WIN * WIN * 255)<=4)?2:((WIN * WIN * 255)<=8)?3:((WIN * WIN * 255)<=16)?4:((WIN * WIN * 255)<=32)?5:((WIN * WIN * 255)<=64)?6:((WIN * WIN * 255)<=128)?7:((WIN * WIN * 255)<=256)?8:((WIN * WIN * 255)<=512)?9:((WIN * WIN * 255)<=1024)?10:((WIN * WIN * 255)<=2048)?11:((WIN * WIN * 255)<=4096)?12:((WIN * WIN * 255)<=8192)?13:((WIN * WIN * 255)<=16384)?14:((WIN * WIN * 255)<=32768)?15:((WIN * WIN * 255)<=65536)?16:((WIN * WIN * 255)<=131072)?17:((WIN * WIN * 255)<=262144)?18:((WIN * WIN * 255)<=524288)?19:((WIN * WIN * 255)<=1048576)?20:((WIN * WIN * 255)<=2097152)?21:((WIN * WIN * 255)<=4194304)?22:((WIN * WIN * 255)<=8388608)?23:((WIN * WIN * 255)<=16777216)?24:((WIN * WIN * 255)<=33554432)?25:((WIN * WIN * 255)<=67108864)?26:((WIN * WIN * 255)<=134217728)?27:((WIN * WIN * 255)<=268435456)?28:((WIN * WIN * 255)<=536870912)?29:((WIN * WIN * 255)<=1073741824)?30:((WIN * WIN * 255)<=2147483648)?31:32) + 1;         // 18  窗口和（灰阶）
    localparam CS2_W = (((WIN * 255 * 255)<=2)?1:((WIN * 255 * 255)<=4)?2:((WIN * 255 * 255)<=8)?3:((WIN * 255 * 255)<=16)?4:((WIN * 255 * 255)<=32)?5:((WIN * 255 * 255)<=64)?6:((WIN * 255 * 255)<=128)?7:((WIN * 255 * 255)<=256)?8:((WIN * 255 * 255)<=512)?9:((WIN * 255 * 255)<=1024)?10:((WIN * 255 * 255)<=2048)?11:((WIN * 255 * 255)<=4096)?12:((WIN * 255 * 255)<=8192)?13:((WIN * 255 * 255)<=16384)?14:((WIN * 255 * 255)<=32768)?15:((WIN * 255 * 255)<=65536)?16:((WIN * 255 * 255)<=131072)?17:((WIN * 255 * 255)<=262144)?18:((WIN * 255 * 255)<=524288)?19:((WIN * 255 * 255)<=1048576)?20:((WIN * 255 * 255)<=2097152)?21:((WIN * 255 * 255)<=4194304)?22:((WIN * 255 * 255)<=8388608)?23:((WIN * 255 * 255)<=16777216)?24:((WIN * 255 * 255)<=33554432)?25:((WIN * 255 * 255)<=67108864)?26:((WIN * 255 * 255)<=134217728)?27:((WIN * 255 * 255)<=268435456)?28:((WIN * 255 * 255)<=536870912)?29:((WIN * 255 * 255)<=1073741824)?30:((WIN * 255 * 255)<=2147483648)?31:32) + 1;         // 21  列和（平方）
    localparam WS2_W = (((WIN * WIN * 255 * 255)<=2)?1:((WIN * WIN * 255 * 255)<=4)?2:((WIN * WIN * 255 * 255)<=8)?3:((WIN * WIN * 255 * 255)<=16)?4:((WIN * WIN * 255 * 255)<=32)?5:((WIN * WIN * 255 * 255)<=64)?6:((WIN * WIN * 255 * 255)<=128)?7:((WIN * WIN * 255 * 255)<=256)?8:((WIN * WIN * 255 * 255)<=512)?9:((WIN * WIN * 255 * 255)<=1024)?10:((WIN * WIN * 255 * 255)<=2048)?11:((WIN * WIN * 255 * 255)<=4096)?12:((WIN * WIN * 255 * 255)<=8192)?13:((WIN * WIN * 255 * 255)<=16384)?14:((WIN * WIN * 255 * 255)<=32768)?15:((WIN * WIN * 255 * 255)<=65536)?16:((WIN * WIN * 255 * 255)<=131072)?17:((WIN * WIN * 255 * 255)<=262144)?18:((WIN * WIN * 255 * 255)<=524288)?19:((WIN * WIN * 255 * 255)<=1048576)?20:((WIN * WIN * 255 * 255)<=2097152)?21:((WIN * WIN * 255 * 255)<=4194304)?22:((WIN * WIN * 255 * 255)<=8388608)?23:((WIN * WIN * 255 * 255)<=16777216)?24:((WIN * WIN * 255 * 255)<=33554432)?25:((WIN * WIN * 255 * 255)<=67108864)?26:((WIN * WIN * 255 * 255)<=134217728)?27:((WIN * WIN * 255 * 255)<=268435456)?28:((WIN * WIN * 255 * 255)<=536870912)?29:((WIN * WIN * 255 * 255)<=1073741824)?30:((WIN * WIN * 255 * 255)<=2147483648)?31:32) + 1;   // 26  窗口和（平方）
    // 【2026-11-02】支持任意 k：判据改为  L²·K2_DEN > K2_NUM·var
    //   k² = K2_NUM/K2_DEN。K2_NUM 非 2 的幂时综合器会用 DSP 做常数乘法
    //   （例如 k=4.47 → K2_NUM=20, K2_DEN=1；k=3.0 → 9/1；k=4.5 → 81/4）
    parameter K2_NUM = K * K;
    parameter K2_DEN = 1;
    localparam KSQ   = K * K;

    reg [CW-1:0] col;
    reg [CH-1:0] row;
    reg [CNT_W-1:0] cnt;                 // 虚拟位置计数
    reg [1:0] state;
    localparam S_RUN = 0, S_DONE = 1;

    integer i;

    // ---- 当前虚拟位置 ----
    wire is_img = (row < H) && (col < W);
    wire [7:0] cur_px  = is_img ? i_data : 8'd0;
    wire [15:0] sq_px  = cur_px * cur_px;

    // 图像位置需要上游给数；PAD 位置自行推进
    wire adv = (state == S_RUN) && (is_img ? i_valid : 1'b1);

    // ---- 两条环形延迟线（全 1 写 1 读）----
    // 盒2 的移出值 = 盒1 移出值取平方（同一像素、同一延迟），所以不再单独存
    // 16 bit 平方流延迟线 rb3（省 20,306×16 = 325 Kbit LUTRAM；
    // 代价是多一个 8×8 乘法器，实测进 CU48E1/DSP，不占 LUT）。
    reg [7:0]  rb1 [0:DEP_A-1];   // cur_px   → 两个盒的移出值（延迟 DLY）
    reg [7:0]  rb2 [0:DEP_B-1];   // cur_px   → 中心像素 x(u)（延迟 CENTER_OFF）

    reg [PA-1:0] wpa, filla;
    reg [PB-1:0] wpb, fillb;

    // ---- 环形延迟线的读地址 ----
    // 组合读版本（USE_BRAM=0）：读 (wp+1) → 当拍拿到 DLY 拍前的数据
    wire [PA-1:0] rpa = (wpa == DEP_A[PA-1:0] - 1'b1) ? {PA{1'b0}} : (wpa + 1'b1);
    wire [PB-1:0] rpb = (wpb == DEP_B[PB-1:0] - 1'b1) ? {PB{1'b0}} : (wpb + 1'b1);
    // 同步读版本（USE_BRAM=1）：地址再 +1（提前一拍取下一拍要的地址），
    // 数据晚一拍出，正好还是同一拍对齐 —— 见文件头推导。
    wire [PA-1:0] rpa2 = (wpa >= (DEP_A[PA-1:0] - 2'd2))
                       ? (wpa + 2'd2 - DEP_A[PA-1:0]) : (wpa + 2'd2);
    wire [PB-1:0] rpb2 = (wpb >= (DEP_B[PB-1:0] - 2'd2))
                       ? (wpb + 2'd2 - DEP_B[PB-1:0]) : (wpb + 2'd2);
    wire full_a = (filla >= DLY[PA-1:0]);            // 延迟 DLY 有效
    wire full_b = (fillb >= CENTER_OFF[PB-1:0]);     // 延迟 CENTER_OFF 有效

    wire [7:0]  d1_old;                              // cur_px(t-DLY)，即 x(r-31, c)
    wire [7:0]  x_mid;                               // x(r-15, c-15) = 窗口中心
    generate
    if (USE_BRAM) begin : g_sync_read
        reg [7:0] d1_q, xm_q;
        always @(posedge clk) begin
            if (!rst_n) begin
                d1_q <= 8'd0;
                xm_q <= 8'd0;
            end else begin
                d1_q <= rb1[rpa2];
                xm_q <= rb2[rpb2];
            end
        end
        assign d1_old = full_a ? d1_q : 8'd0;
        assign x_mid  = full_b ? xm_q : 8'd0;
    end else begin : g_comb_read
        assign d1_old = full_a ? rb1[rpa] : 8'd0;
        assign x_mid  = full_b ? rb2[rpb] : 8'd0;
    end
    endgenerate
    wire [15:0] d2_old = d1_old * d1_old;            // 同一像素的平方（等价于原 rb3 读出）

    // ---- 列和数组（1 写 1 读；不复位，row!=0 门控首次读为 0）----
    reg [CS1_W-1:0] cs1 [0:W15-1];
    reg [CS2_W-1:0] cs2 [0:W15-1];

    wire [CS1_W-1:0] cs1_rd = (row != 0) ? cs1[col] : {CS1_W{1'b0}};
    wire [CS2_W-1:0] cs2_rd = (row != 0) ? cs2[col] : {CS2_W{1'b0}};
    wire [CS1_W-1:0] ncs1 = cs1_rd + {5'd0, cur_px}  - {5'd0, d1_old};
    wire [CS2_W-1:0] ncs2 = cs2_rd + {5'd0, sq_px}   - {5'd0, d2_old};

    // ---- 水平 31 项（每项是一列的竖直和）----
    reg [CS1_W-1:0] f1 [0:WIN-1];
    reg [CS2_W-1:0] f2 [0:WIN-1];

    wire [WS1_W-1:0] ws1 = ncs1
        + f1[0]  + f1[1]  + f1[2]  + f1[3]  + f1[4]  + f1[5]  + f1[6]  + f1[7]
        + f1[8]  + f1[9]  + f1[10] + f1[11] + f1[12] + f1[13] + f1[14] + f1[15]
        + f1[16] + f1[17] + f1[18] + f1[19] + f1[20] + f1[21] + f1[22] + f1[23]
        + f1[24] + f1[25] + f1[26] + f1[27] + f1[28] + f1[29];
    wire [WS2_W-1:0] ws2 = ncs2
        + f2[0]  + f2[1]  + f2[2]  + f2[3]  + f2[4]  + f2[5]  + f2[6]  + f2[7]
        + f2[8]  + f2[9]  + f2[10] + f2[11] + f2[12] + f2[13] + f2[14] + f2[15]
        + f2[16] + f2[17] + f2[18] + f2[19] + f2[20] + f2[21] + f2[22] + f2[23]
        + f2[24] + f2[25] + f2[26] + f2[27] + f2[28] + f2[29];

    // ---- 裁剪面积 A（按中心 u = (row-15, col-15) 裁剪，与 PS 侧 max/min 一致）----
    wire [CH-1:0] cr = row - HALF;
    wire [CW-1:0] cc = col - HALF;
    wire [5:0] cnt_r = (cr < HALF) ? (cr + HALF + 1)
                     : ((cr >= H - HALF) ? (H + HALF - cr) : WIN_V);
    wire [5:0] cnt_c = (cc < HALF) ? (cc + HALF + 1)
                     : ((cc >= W - HALF) ? (W + HALF - cc) : WIN_V);
    wire [11:0] area_raw = cnt_r * cnt_c;
    wire [A_W-1:0] area_c = (area_raw == 12'd0) ? 11'd1 : area_raw[A_W-1:0];

    // ---- 判决流水线（4 级；为 100 MHz 时序而拆）----------------------------
    // 判决式：(x·A - S1 - FLOOR·A)² > K²·(A·S2 - S1²)
    //   原实现把「31 项加法树 → 乘法 → 减法 → 平方 → 比较」全压在一个时钟里，
    //   100 MHz（10 ns）绝对不可能收敛（两级 20 位乘法器串联）。
    //   现拆成 4 级，每级之间一个寄存器：
    //     L0 组合 : 31 项加法树 → ws1 / ws2（本拍）
    //     L1 寄存器: ws1²、A·ws2、x·A、FLOOR·A          （每项只是一次乘法）
    //     L2 寄存器: A·S2−S1²、K²·var（K=4 → 左移 4）、L 与 |L|（只是减法）
    //     L3 寄存器: detect = (L>0) && (L² > K²·var)     （一次乘法 + 比较）
    //   x_mid（o_enh）与 out_gate（o_valid）同步延迟 4 拍对齐。
    reg [WS1_W-1:0] q1_ws1;
    reg [WS2_W-1:0] q1_ws2;
    reg [A_W-1:0]   q1_area;
    reg  [7:0]      q1_x;
    reg             q1_gate;

    reg [35:0]      q2_s1sq;   // ws1²
    reg [36:0]      q2_as2;    // A·ws2
    reg [19:0]      q2_xa;     // x·A
    reg [19:0]      q2_fa;     // FLOOR·A
    reg [WS1_W-1:0] q2_ws1;    // 与 q2_xa 对齐的 S1
    reg  [7:0]      q2_x;
    reg             q2_gate;

    reg [40:0]      q3_lim;    // K²·(A·S2 − S1²)
    reg [19:0]      q3_lmag;   // |L|
    reg             q3_lpos;   // L > 0
    reg  [7:0]      q3_x;
    reg             q3_gate;

    reg             q4_det;
    reg  [7:0]      q4_x;
    reg             q4_gate;

    // L1 组合：乘法
    wire [35:0] q2_s1sq_w = q1_ws1 * q1_ws1;
    wire [36:0] q2_as2_w  = q1_area * q1_ws2;
    wire [19:0] q2_xa_w   = {12'd0, q1_x} * q1_area;
    wire [19:0] q2_fa_w   = FLOOR * q1_area;

    // L2 组合：减法 / 移位
    wire [36:0] q3_var_w  = (q2_as2 >= {1'b0, q2_s1sq}) ? (q2_as2 - {1'b0, q2_s1sq}) : 37'd0;
    wire [40:0] q3_lim_w  = q3_var_w * K2_NUM;          // K2_NUM·var（非常数幂时走 DSP）
    wire [19:0] q3_lb_w   = {2'd0, q2_ws1} + q2_fa;     // S1 + FLOOR·A
    wire        q3_lpos_w = (q2_xa > q3_lb_w);
    wire [19:0] q3_lmag_w = q3_lpos_w ? (q2_xa - q3_lb_w) : 20'd0;

    // L3 组合：平方 + 比较
    wire [37:0] q4_lsq_w  = q3_lmag * q3_lmag;
    wire [47:0] q4_lsqd_w = q4_lsq_w * K2_DEN;          // K2_DEN=1 时综合成直连
    wire        q4_det_w  = q3_lpos && ({10'd0, q4_lsqd_w} > q3_lim);

    // 输出位置 u=(row-15,col-15)：row∈[15,H+15)、col∈[15,W+15) 恰好 H×W 个
    wire out_gate = (row >= HALF) && (col >= HALF) &&
                    (row < H + HALF) && (col < W + HALF);

    reg [7:0] o_data_r;
    reg [7:0] o_enh_r;
    reg o_valid_r;

    // ---- 判决流水线寄存器：每拍都推进（帧尾把在途结果排空），只在 adv 采新值 ----
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            q1_ws1 <= 0; q1_ws2 <= 0; q1_area <= 0; q1_x <= 0; q1_gate <= 1'b0;
            q2_s1sq <= 0; q2_as2 <= 0; q2_xa <= 0; q2_fa <= 0;
            q2_ws1 <= 0; q2_x <= 0; q2_gate <= 1'b0;
            q3_lim <= 0; q3_lmag <= 0; q3_lpos <= 1'b0; q3_x <= 0; q3_gate <= 1'b0;
            q4_det <= 1'b0; q4_x <= 0; q4_gate <= 1'b0;
            o_data_r <= 8'd0; o_enh_r <= 8'd0; o_valid_r <= 1'b0;
        end else begin
            if (adv) begin
                q1_ws1  <= ws1;
                q1_ws2  <= ws2;
                q1_area <= area_c;
                q1_x    <= x_mid;
                q1_gate <= out_gate;
            end else begin
                // 空隙：整组清零（否则 q1 保持旧值，下一拍 q2 会重复采到同一个样本，
                // 导致流水线错位）
                q1_ws1  <= 0;
                q1_ws2  <= 0;
                q1_area <= 0;
                q1_x    <= 0;
                q1_gate <= 1'b0;      // 空隙填 0，保证 o_valid 恰好 H×W 拍
            end

            q2_s1sq <= q2_s1sq_w;
            q2_as2  <= q2_as2_w;
            q2_xa   <= q2_xa_w;
            q2_fa   <= q2_fa_w;
            q2_ws1  <= q1_ws1;
            q2_x    <= q1_x;
            q2_gate <= q1_gate;

            q3_lim  <= q3_lim_w;
            q3_lmag <= q3_lmag_w;
            q3_lpos <= q3_lpos_w;
            q3_x    <= q2_x;
            q3_gate <= q2_gate;

            q4_det  <= q4_det_w;
            q4_x    <= q3_x;
            q4_gate <= q3_gate;

            o_data_r  <= q4_det ? 8'd255 : 8'd0;
            o_enh_r   <= q4_x;
            o_valid_r <= q4_gate;
        end
    end

    // ---- 环形线写块（独立 always，供综合器推断 RAM）----
    // 【Vivado 兼容】三个 RAM 写块都改成**同步复位**（always @(posedge clk)）：
    //   Vivado 报 [Synth 8-3391] "RAM is sensitive to asynchronous reset signal"
    //   会拒绝推断 RAM（Procise/Verific 两种都接受）。rst_n 由上层同步产生。
    always @(posedge clk) begin
        if (!rst_n) begin
            wpa <= 0; filla <= 0;
        end else if (adv) begin
            rb1[wpa] <= cur_px;
            if (wpa == DEP_A[PA-1:0] - 1'b1) wpa <= {PA{1'b0}};
            else                             wpa <= wpa + 1'b1;
            if (filla < DEP_A[PA-1:0]) filla <= filla + 1'b1;
        end
    end
    // 中心像素延迟线
    always @(posedge clk) begin
        if (!rst_n) begin
            wpb <= 0; fillb <= 0;
        end else if (adv) begin
            rb2[wpb] <= cur_px;
            if (wpb == DEP_B[PB-1:0] - 1'b1) wpb <= {PB{1'b0}};
            else                             wpb <= wpb + 1'b1;
            if (fillb < DEP_B[PB-1:0]) fillb <= fillb + 1'b1;
        end
    end
    // 列和数组（同址读旧值 + 写；不复位，避免复位影响 RAM 推断）
    always @(posedge clk) begin
        if (adv) begin
            cs1[col] <= ncs1;
            cs2[col] <= ncs2;
        end
    end

    // ---- 状态机：fifo 移位、坐标推进、输出寄存 ----
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i < WIN; i = i + 1) begin f1[i] <= 0; f2[i] <= 0; end
            col <= 0; row <= 0; cnt <= 0; state <= S_RUN;
        end else begin
            if (adv) begin
                f1[0] <= ncs1;
                f2[0] <= ncs2;
                if (col == 0) begin
                    for (i = 1; i < WIN; i = i + 1) begin f1[i] <= 0; f2[i] <= 0; end
                end else begin
                    for (i = 1; i < WIN; i = i + 1) begin f1[i] <= f1[i-1]; f2[i] <= f2[i-1]; end
                end

                if (cnt == N_EXT - 1) state <= S_DONE;
                else begin
                    cnt <= cnt + 1;
                    if (col == W15 - 1) begin col <= 0; row <= row + 1; end
                    else                     col <= col + 1;
                end
            end
        end
    end

    assign i_ready = (state == S_RUN) && is_img;
    assign o_data  = o_data_r;
    assign o_enh   = o_enh_r;
    assign o_valid = o_valid_r;
endmodule
