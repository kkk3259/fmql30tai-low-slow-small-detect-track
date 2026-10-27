// candidate_extract_stream.v —— 流式候选提取（单趟扫描 CCL + 并查集）
//
// 【重构要点】替代原来的"两遍扫描 + 三块全帧 BRAM(bin/enh/label)"方案。
//   单趟光栅扫描：每个像素到来时立即
//     1) 看左上/上/右上/左 4 个因果邻居标签，无前景邻居→新标签，有→取最小并 union
//     2) 直接把 area/sum_x/sum_y/peak 累加到该像素"被赋的标签"上
//     3) 标签写入当前行标签数组（只需两行 W 个标签，不再需要全帧 label_bram）
//   帧扫描结束后 S_MERGE 把每个标签的累加量并入其根标签，
//   再 S_SORT（按 peak 降序选择排序）、S_OUT 输出 36 字节候选列表（与旧版逐字节一致）。
//
//   片上存储：0（本模块不再有任何全帧存储，只有 2×W 个标签 + MAX_COMP 组累加器）
module candidate_extract_stream #(
    parameter W = 64,
    parameter H = 64,
    parameter MAX_CAND = 5,
    parameter MAX_COMP = 64,
    parameter MIN_AREA = 2,
    parameter MAX_AREA = 200
)(
    input  wire clk,
    input  wire rst_n,
    input  wire i_bin,          // 二值图（1=前景）
    input  wire i_bin_valid,
    input  wire [7:0] i_enh,    // 增强图（算 peak）
    input  wire i_enh_valid,
    input  wire o_ready,
    output wire [7:0] o_data,
    output wire o_valid,
    // ---- 调试用（可不接）：当前状态机状态 + 已扫像素计数 ----
    output wire [2:0]  dbg_state,
    output wire [17:0] dbg_px,
    // 调试：CCL 内部实际数到的 i_bin_valid 个数（判定 valid 是否真连到本模块）
    output wire [31:0] dbg_vcnt
);
    localparam N = W * H;
    localparam CNT_W = $clog2(N + 1);
    localparam CW = $clog2(W + 1);
    localparam CH = $clog2(H + 1);
    localparam LW = $clog2(MAX_COMP + 1);   // 标签位宽（0=背景）

    // 行标签缓存见下方 lbl_ram（1 写 2 读的双口 RAM）。
    // 原实现是 lbl_even/lbl_odd 两个 W 项寄存器数组 + 三个 W:1 组合 mux，
    // 实测吃掉约 2.6 万 LUT（占整设计 60%），是布局失败的直接原因。

    reg [LW-1:0] left_lbl;               // 左邻居标签
    reg [LW-1:0] n_lbl;                  // 已用标签数（0 基，标签 = n_lbl+1）
    reg [LW-1:0] parent [0:MAX_COMP-1];  // 并查集父指针（parent[i]=标签 i+1 的父，自身=根）

    reg [15:0] carea [0:MAX_COMP-1];
    reg [15:0] csumx [0:MAX_COMP-1];
    reg [15:0] csumy [0:MAX_COMP-1];
    reg [7:0]  cpeak [0:MAX_COMP-1];

    reg [15:0] cx [0:MAX_COMP-1];
    reg [15:0] cy [0:MAX_COMP-1];
    reg [7:0]  n_comp;
    reg [5:0]  cnt;

    reg [CNT_W-1:0] px_cnt;
    reg [CW-1:0] col;
    reg [CH-1:0] row;
    reg [6:0] mk;                  // S_MERGE 标签游标
    reg [6:0] pi;                  // S_POST 标签游标

    // ---- S_POST 串行除法器（每拍 1 位移位相减）----
    // 【2026-10-26 重写】原写法 `cx[pi] <= (csumx[pi]+carea[pi]/2)/carea[pi]`
    //   是单周期 16/8 位变量除法，综合出 104 级逻辑、-12.2ns（50MHz 下过不去）。
    //   改成串行：每个标签算 cx 17 拍 + cy 17 拍，64 个标签 ≈ 2400 拍
    //   （50MHz 下 48us，相对一帧 23 万拍可忽略）。
    //   dv_step: 0=装载cx 1..17=迭代cx 18=写cx/装载cy 19..35=迭代cy 36=写cy
    reg [5:0]  dv_step;
    reg [18:0] dv_rem;
    reg [16:0] dv_num;             // 被除数（csum + 面积/2，最大 127800+100 < 2^17）
    reg [16:0] dv_q;
    reg [7:0]  dv_div;
    reg [2:0] state;
    localparam S_RUN = 0, S_MERGE = 1, S_POST = 2, S_SORT = 3, S_OUT = 4, S_DONE = 5;

    integer i;

    // ---- 因果邻居标签（8 连通：左上、上、右上、左）----
    wire par = row[0];

    // ---- 行标签缓存：1 写 2 异步读的 LUTRAM，两块 bank 按行奇偶分 ----
    //   写地址 {bank, col}（本行，同步写）；读地址 {~bank, col}/{ ~bank, col+1}（上一行，异步读）
    //   用动态读写才能被推成 RAM；写成寄存器数组的话读口会变成 W:1 大 mux。
    localparam AW = $clog2(2 * W);
    localparam [AW-1:0] W_AW = W;
    reg [LW-1:0] lbl_ram [0:2*W-1];
    reg [LW-1:0] prev_t_d;                     // prev_t 打一拍 = prev_ul

    wire [CW-1:0] col_r    = (col == W - 1) ? col : (col + 1'b1);
    wire [AW-1:0] wr_addr  = (par     ? W_AW : {AW{1'b0}}) + {{(AW-CW){1'b0}}, col};
    wire [AW-1:0] rd_addr_t = ((~par) ? W_AW : {AW{1'b0}}) + {{(AW-CW){1'b0}}, col};
    wire [AW-1:0] rd_addr_r = ((~par) ? W_AW : {AW{1'b0}}) + {{(AW-CW){1'b0}}, col_r};

    // 第 0 行没有“上一行”，把读口整体屏蔽为 0（RAM 本身不复位，靠这个门控避免读 X）
    wire row_has_prev = (row != 0);
    wire [LW-1:0] prev_ul = (row_has_prev && col > 0)     ? prev_t_d : {LW{1'b0}};
    wire [LW-1:0] prev_t  = row_has_prev                  ? lbl_ram[rd_addr_t] : {LW{1'b0}};
    wire [LW-1:0] prev_ur = (row_has_prev && col < W - 1) ? lbl_ram[rd_addr_r] : {LW{1'b0}};
    wire [LW-1:0] nb_l    = left_lbl;

    function [LW-1:0] min4;
        input [LW-1:0] a, b, c, d;
        reg [LW-1:0] m;
        begin
            m = {LW{1'b0}};
            if (a != 0) m = a;
            if (b != 0 && (m == 0 || b < m)) m = b;
            if (c != 0 && (m == 0 || c < m)) m = c;
            if (d != 0 && (m == 0 || d < m)) m = d;
            min4 = m;
        end
    endfunction

    wire [LW-1:0] min_nb = min4(prev_ul, prev_t, prev_ur, nb_l);
    // 本像素被赋的标签
    wire [LW-1:0] new_lbl    = (min_nb != {LW{1'b0}}) ? min_nb
                             : ((n_lbl < MAX_COMP - 1) ? n_lbl + 1'b1 : {LW{1'b0}});
    wire [LW-1:0] assign_lbl = i_bin ? new_lbl : {LW{1'b0}};

    // ------------------------------------------------------------------
    // S_MERGE：把每个标签的累加量并入父标签
    //
    // 【2026-10-26 重写】原实现用 find_root() 在单拍内展开最多 MAX_COMP(64)
    //   次父指针遍历，综合后是一条 391 级逻辑、-225.8ns 的组合长路径
    //   （最优路径：parent_reg[34][2]/CK -> carea[28]_reg[12]/CE）。
    //
    //   新实现利用并查集的不变式：parent[x] < x（并时总指向 min_nb，且
    //   当 min_nb == x 时不写），所以按标签号【从大到小】处理时，每个
    //   标签的子孙都已处理完毕，直接把它的总量并给父标签即可，父标签
    //   在更晚的拍被处理，最终所有量必然汇聚到根上。
    //   每拍只做一次 64:1 查表 + 加法，逻辑深度降到几级。
    //   mk 仍从 0 升序计数，用 mg_idx = (MAX_COMP-1) - mk 取实际标签索引。
    // ------------------------------------------------------------------
    wire [6:0]    mg_idx   = (MAX_COMP - 1) - mk;        // 实际处理的标签索引（降序）
    wire [LW-1:0] mg_lbl   = mg_idx[LW-1:0] + 1'b1;      // 标签号 1..MAX_COMP
    wire [LW-1:0] mg_par   = parent[mg_idx];
    wire          mg_child = (mg_par != mg_lbl) && (mg_par != {LW{1'b0}}) && (carea[mg_idx] != 0);

    // ---- S_POST 串行除法器组合部分 ----
    wire [18:0] dv_rem_sh = {dv_rem[17:0], dv_num[16]};
    wire        dv_ge     = (dv_rem_sh >= {11'd0, dv_div});
    wire [18:0] dv_rem_nx = dv_ge ? (dv_rem_sh - {11'd0, dv_div}) : dv_rem_sh;
    // 被除数 = 累加和 + 面积/2（四舍五入），源数据同拍组合
    wire [16:0] dv_num_x  = {1'b0, csumx[pi]} + {11'd0, carea[pi][7:0]} / 2;
    wire [16:0] dv_num_y  = {1'b0, csumy[pi]} + {11'd0, carea[pi][7:0]} / 2;
    wire [7:0]  dv_div_w  = (carea[pi][7:0] == 8'd0) ? 8'd1 : carea[pi][7:0];

    // 输出字段选择（36 字节：n_cand + 5×(x_hi,x_lo,y_hi,y_lo,area_hi,area_lo,peak)）
    wire [5:0] out_idx = cnt[5:0];
    wire [2:0] cand_i  = (out_idx - 7'd1) / 3'd7;
    wire [2:0] field   = (out_idx - 7'd1) % 3'd7;
    wire [15:0] x16 = cx[cand_i];
    wire [15:0] y16 = cy[cand_i];
    reg [7:0] out_val;
    always @* begin
        if (out_idx == 6'd0)
            out_val = (n_comp < MAX_CAND) ? n_comp : MAX_CAND[7:0];
        else if (cand_i >= n_comp)
            out_val = 8'd0;
        else case (field)
            3'd0: out_val = x16[15:8];
            3'd1: out_val = x16[7:0];
            3'd2: out_val = y16[15:8];
            3'd3: out_val = y16[7:0];
            3'd4: out_val = 8'd0;                 // area 高字节恒 0（area<=200<256）
            3'd5: out_val = carea[cand_i][7:0];
            3'd6: out_val = cpeak[cand_i];
            default: out_val = 8'd0;
        endcase
    end

    // 有效组件数（组合计数）
    reg [7:0] n_comp_c;
    always @* begin
        n_comp_c = 8'd0;
        for (i = 0; i < MAX_COMP; i = i + 1) begin
            if (carea[i] >= MIN_AREA && carea[i] <= MAX_AREA)
                n_comp_c = n_comp_c + 8'd1;
        end
    end

    reg [3:0] si;
    reg [6:0] sj;
    reg [5:0] mi;
    reg [7:0] maxp;
    reg [1:0] sort_phase;

    reg [7:0] o_data_r;
    reg o_valid_r;

    // ---- 行标签 RAM 的写口：必须是独立 always 块（写进状态机 case 里 Procise 就不认 RAM）----
    always @(posedge clk) begin
        if (state == S_RUN && i_bin_valid)
            lbl_ram[wr_addr] <= assign_lbl;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            prev_t_d <= 0;
            for (i = 0; i < MAX_COMP; i = i + 1) begin
                parent[i] <= i + 1; carea[i] <= 0; csumx[i] <= 0; csumy[i] <= 0; cpeak[i] <= 0;
                cx[i] <= 0; cy[i] <= 0;
            end
            left_lbl <= 0; n_lbl <= 0; n_comp <= 0;
            col <= 0; row <= 0; cnt <= 0; px_cnt <= 0; mk <= 0; pi <= 0;
            dv_step <= 0; dv_rem <= 0; dv_num <= 0; dv_q <= 0; dv_div <= 8'd1;
            state <= S_RUN;
            o_data_r <= 0; o_valid_r <= 0;
        end else begin
            o_valid_r <= 1'b0;
            case (state)
            S_RUN: begin
                if (i_bin_valid) begin
                    // 1) 行缓存写标签（写口在下面独立的 always 块里，否则推不成 RAM）
                    left_lbl <= assign_lbl;
                    prev_t_d <= prev_t;              // 供下一列作 prev_ul

                    // 2) 标签管理与 union
                    if (i_bin && assign_lbl != 0) begin
                        if (min_nb == {LW{1'b0}}) begin
                            if (n_lbl < MAX_COMP - 1) n_lbl <= n_lbl + 1'b1;
                        end else begin
                            if (prev_ul != 0 && prev_ul != min_nb) parent[prev_ul-1] <= min_nb;
                            if (prev_t  != 0 && prev_t  != min_nb) parent[prev_t -1] <= min_nb;
                            if (prev_ur != 0 && prev_ur != min_nb) parent[prev_ur-1] <= min_nb;
                            if (nb_l    != 0 && nb_l    != min_nb) parent[nb_l   -1] <= min_nb;
                        end
                        // 3) 立即累加到被赋标签
                        carea[assign_lbl-1] <= carea[assign_lbl-1] + 16'd1;
                        csumx[assign_lbl-1] <= csumx[assign_lbl-1] + {{(16-CW){1'b0}}, col};
                        csumy[assign_lbl-1] <= csumy[assign_lbl-1] + {{(16-CH){1'b0}}, row};
                        if (i_enh > cpeak[assign_lbl-1]) cpeak[assign_lbl-1] <= i_enh;
                    end

                    // 4) 光栅推进
                    if (px_cnt == N - 1) begin
                        state <= S_MERGE; mk <= 0;
                    end else begin
                        px_cnt <= px_cnt + 1'b1;
                        if (col == W - 1) begin col <= 0; row <= row + 1'b1; left_lbl <= 0; end
                        else col <= col + 1'b1;
                    end
                end
            end
            S_MERGE: begin
                // 把子标签的累加量并入【父标签】（父标签编号恒小于子标签；
                // 本拍处理的是降序索引 mg_idx，故子孙已先行并入，量会逐级汇聚到根）
                if (mg_child) begin
                    carea[mg_par-1] <= carea[mg_par-1] + carea[mg_idx];
                    csumx[mg_par-1] <= csumx[mg_par-1] + csumx[mg_idx];
                    csumy[mg_par-1] <= csumy[mg_par-1] + csumy[mg_idx];
                    if (cpeak[mg_idx] > cpeak[mg_par-1]) cpeak[mg_par-1] <= cpeak[mg_idx];
                    carea[mg_idx] <= 0; csumx[mg_idx] <= 0; csumy[mg_idx] <= 0; cpeak[mg_idx] <= 0;
                end
                if (mk >= MAX_COMP - 1) begin
                    state <= S_POST; pi <= 0; dv_step <= 0;
                end else mk <= mk + 7'd1;
            end
            S_POST: begin
                // 有效组件算重心（整数除法，四舍五入），无效组件清零
                // （peak 清 0 使其在排序中落到底部）。
                // 【2026-10-26】除法改成串行移位相减，避免单周期 104 级组合逻辑。
                case (dv_step)
                6'd0: begin
                    if (pi == 0) n_comp <= n_comp_c;
                    if (carea[pi] >= MIN_AREA && carea[pi] <= MAX_AREA) begin
                        dv_div  <= dv_div_w;
                        dv_num  <= dv_num_x;
                        dv_rem  <= 19'd0;
                        dv_q    <= 17'd0;
                        dv_step <= 6'd1;
                    end else begin
                        cx[pi] <= 16'd0; cy[pi] <= 16'd0; cpeak[pi] <= 8'd0;
                        if (pi >= MAX_COMP - 1) begin
                            state <= S_SORT; si <= 0; sort_phase <= 0;
                        end else begin
                            pi <= pi + 7'd1;
                        end
                    end
                end
                6'd18: begin
                    cx[pi]  <= dv_q[15:0];
                    dv_num  <= dv_num_y;
                    dv_rem  <= 19'd0;
                    dv_q    <= 17'd0;
                    dv_step <= 6'd19;
                end
                6'd36: begin
                    cy[pi]  <= dv_q[15:0];
                    dv_step <= 6'd0;
                    if (pi >= MAX_COMP - 1) begin
                        state <= S_SORT; si <= 0; sort_phase <= 0;
                    end else begin
                        pi <= pi + 7'd1;
                    end
                end
                default: begin
                    dv_rem  <= dv_rem_nx;
                    dv_q    <= {dv_q[15:0], dv_ge};
                    dv_num  <= {dv_num[15:0], 1'b0};
                    dv_step <= (dv_step == 6'd17) ? 6'd18
                             : ((dv_step == 6'd35) ? 6'd36 : (dv_step + 6'd1));
                end
                endcase
            end
            S_SORT: begin
                if (sort_phase == 2'd0) begin
                    sj <= si; mi <= si; maxp <= cpeak[si];
                    // 重心与面积标定（原 S_ACCUM 尾部的收尾计算搬到这里之前完成）
                    sort_phase <= 2'd1;
                end else if (sort_phase == 2'd1) begin
                    if (sj < MAX_COMP) begin
                        if (cpeak[sj] > maxp) begin maxp <= cpeak[sj]; mi <= sj; end
                        sj <= sj + 7'd1;
                    end else begin
                        cx[si] <= cx[mi]; cx[mi] <= cx[si];
                        cy[si] <= cy[mi]; cy[mi] <= cy[si];
                        carea[si] <= carea[mi]; carea[mi] <= carea[si];
                        cpeak[si] <= cpeak[mi]; cpeak[mi] <= cpeak[si];
                        sort_phase <= 2'd2;
                    end
                end else begin
                    si <= si + 4'd1;
                    if (si + 4'd1 < n_comp && si + 4'd1 < MAX_CAND) sort_phase <= 2'd0;
                    else begin state <= S_OUT; cnt <= 0; end
                end
            end
            S_OUT: begin
                o_valid_r <= 1'b1;
                o_data_r <= out_val;
                if (o_ready) begin
                    if (out_idx == 6'd35) state <= S_DONE;
                    else cnt <= cnt + 1'b1;
                end
            end
            S_DONE: state <= S_DONE;
            endcase
        end
    end

    assign o_data  = o_data_r;
    assign o_valid = o_valid_r;

    // 调试探针（放在最后，iverilog 要求先声明后使用）
    assign dbg_state = state;
    assign dbg_px    = px_cnt;

    // CCL 内部 valid 计数：与顶层 cf_valid 计数对比，
    //   两者相等 => valid 网络连上了；CCL 侧为 0 而顶层不为 0 => 连线/位宽问题。
    reg [31:0] vcnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)          vcnt <= 32'd0;
        else if (i_bin_valid) vcnt <= vcnt + 32'd1;
    end
    assign dbg_vcnt = vcnt;
endmodule
