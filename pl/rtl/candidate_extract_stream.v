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
    output wire o_valid
);
    localparam N = W * H;
    localparam CNT_W = $clog2(N + 1);
    localparam CW = $clog2(W + 1);
    localparam CH = $clog2(H + 1);
    localparam LW = $clog2(MAX_COMP + 1);   // 标签位宽（0=背景）

    // 当前行 / 上一行标签（行奇偶双缓冲，避免整行拷贝）
    reg [LW-1:0] lbl_even [0:W-1];
    reg [LW-1:0] lbl_odd  [0:W-1];

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
    reg [2:0] state;
    localparam S_RUN = 0, S_MERGE = 1, S_POST = 2, S_SORT = 3, S_OUT = 4, S_DONE = 5;

    integer i;

    // ---- 因果邻居标签（8 连通：左上、上、右上、左）----
    wire par = row[0];
    wire [LW-1:0] prev_ul = (col > 0)     ? (par ? lbl_even[col - 1] : lbl_odd[col - 1]) : {LW{1'b0}};
    wire [LW-1:0] prev_t  =                   (par ? lbl_even[col]     : lbl_odd[col]);
    wire [LW-1:0] prev_ur = (col < W - 1) ? (par ? lbl_even[col + 1] : lbl_odd[col + 1]) : {LW{1'b0}};
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

    function [LW-1:0] find_root;
        input [LW-1:0] l;
        reg [LW-1:0] x;
        integer k;
        begin
            x = l;
            if (x != 0 && x <= MAX_COMP) begin
                for (k = 0; k < MAX_COMP; k = k + 1) begin
                    if (parent[x-1] != 0 && parent[x-1] != x && parent[x-1] <= MAX_COMP)
                        x = parent[x-1];
                end
            end
            find_root = x;
        end
    endfunction

    wire [LW-1:0] min_nb = min4(prev_ul, prev_t, prev_ur, nb_l);
    // 本像素被赋的标签
    wire [LW-1:0] new_lbl    = (min_nb != {LW{1'b0}}) ? min_nb
                             : ((n_lbl < MAX_COMP - 1) ? n_lbl + 1'b1 : {LW{1'b0}});
    wire [LW-1:0] assign_lbl = i_bin ? new_lbl : {LW{1'b0}};

    // S_MERGE：标签 mk+1 的根
    wire [LW-1:0] mk_lbl   = mk[LW-1:0] + 1'b1;
    wire [LW-1:0] mk_root  = (mk < MAX_COMP) ? find_root(mk_lbl) : {LW{1'b0}};
    wire          mk_child = (mk < MAX_COMP) && (mk_root != mk_lbl) && (carea[mk] != 0);

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

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i < W; i = i + 1) begin lbl_even[i] <= 0; lbl_odd[i] <= 0; end
            for (i = 0; i < MAX_COMP; i = i + 1) begin
                parent[i] <= i + 1; carea[i] <= 0; csumx[i] <= 0; csumy[i] <= 0; cpeak[i] <= 0;
                cx[i] <= 0; cy[i] <= 0;
            end
            left_lbl <= 0; n_lbl <= 0; n_comp <= 0;
            col <= 0; row <= 0; cnt <= 0; px_cnt <= 0; mk <= 0;
            state <= S_RUN;
            o_data_r <= 0; o_valid_r <= 0;
        end else begin
            o_valid_r <= 1'b0;
            case (state)
            S_RUN: begin
                if (i_bin_valid) begin
                    // 1) 行缓存写标签
                    if (par) lbl_odd[col] <= assign_lbl;
                    else     lbl_even[col] <= assign_lbl;
                    left_lbl <= assign_lbl;

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
                // 把子标签的累加量并入根标签（根标签编号恒小于子标签，故按升序处理一次即可）
                if (mk_child) begin
                    carea[mk_root-1] <= carea[mk_root-1] + carea[mk];
                    csumx[mk_root-1] <= csumx[mk_root-1] + csumx[mk];
                    csumy[mk_root-1] <= csumy[mk_root-1] + csumy[mk];
                    if (cpeak[mk] > cpeak[mk_root-1]) cpeak[mk_root-1] <= cpeak[mk];
                    carea[mk] <= 0; csumx[mk] <= 0; csumy[mk] <= 0; cpeak[mk] <= 0;
                end
                if (mk >= MAX_COMP - 1) begin
                    state <= S_POST;
                end else mk <= mk + 7'd1;
            end
            S_POST: begin
                // 与旧版 S_ACCUM 尾部一致：有效组件算重心，无效组件清零（peak 清 0 让排序落到底部）
                n_comp <= n_comp_c;
                for (i = 0; i < MAX_COMP; i = i + 1) begin
                    if (carea[i] >= MIN_AREA && carea[i] <= MAX_AREA) begin
                        cx[i] <= (csumx[i] + carea[i]/16'd2) / carea[i];
                        cy[i] <= (csumy[i] + carea[i]/16'd2) / carea[i];
                    end else begin
                        cx[i] <= 0; cy[i] <= 0; cpeak[i] <= 0;
                    end
                end
                state <= S_SORT; si <= 0; sort_phase <= 0;
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
endmodule
