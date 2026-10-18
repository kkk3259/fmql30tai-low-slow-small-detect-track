// candidate_extract_stream.v —— 流式候选提取（两遍扫描 CCL + 并查集，综合友好）
//
// 【重构要点】替代 DFS 洪泛（组合逻辑随机访问 bin[nyu][nxu]，综合器推不出）。
//   两遍扫描（8 连通，全程顺序访问 BRAM）：
//     S_LOAD 存 bin/enh 两帧
//     S_LABEL 逐行扫描，看左上/上/右上/左 4 邻居；无前景邻居→新标签，有→取最小并记录 union；标签存 label_bram
//     S_UNION 并查集路径减半压缩（多轮）得到最终根
//     S_ACCUM 逐像素读 label_bram 解析根，累加 area、sum_x、sum_y、peak
//     S_SORT  选择排序按 peak 降序；S_OUT 输出 36 字节候选列表（与 candidate_extract.v 一致）
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

    reg [0:0] bin_bram [0:N-1];
    reg [7:0] enh_bram [0:N-1];
    reg [LW-1:0] label_bram [0:N-1];     // Pass1 临时标签

    reg [LW-1:0] prev_lbl [0:W-1];       // 上一行标签
    reg [LW-1:0] left_lbl;               // 左邻居标签
    reg [LW-1:0] n_lbl;                  // 已用标签数（0 基，标签 = n_lbl+1）
    reg [LW-1:0] parent [0:MAX_COMP-1];  // 并查集父指针（parent[i]=标签 i+1 的父，1 基）

    reg [15:0] carea [0:MAX_COMP-1];
    reg [15:0] csumx [0:MAX_COMP-1];
    reg [15:0] csumy [0:MAX_COMP-1];
    reg [7:0]  cpeak [0:MAX_COMP-1];

    reg [15:0] cx [0:MAX_COMP-1];
    reg [15:0] cy [0:MAX_COMP-1];
    reg [7:0]  n_comp;
    reg [5:0]  cnt;

    reg [CNT_W-1:0] scan;
    reg [CNT_W-1:0] bin_cnt, enh_cnt;
    reg bin_loaded, enh_loaded;
    reg [CW-1:0] col;
    reg [CH-1:0] row;
    reg [CNT_W-1:0] ucnt;
    reg [2:0] state;
    localparam S_LOAD = 0, S_LABEL = 1, S_UNION = 2, S_ACCUM = 3, S_SORT = 4, S_OUT = 5, S_DONE = 6;

    integer i;

    // 邻居标签（8 连通：左上、上、右上、左）
    wire [LW-1:0] nb_ul = (col > 0) ? prev_lbl[col - 1] : {LW{1'b0}};
    wire [LW-1:0] nb_t  = prev_lbl[col];
    wire [LW-1:0] nb_ur = (col < W - 1) ? prev_lbl[col + 1] : {LW{1'b0}};
    wire [LW-1:0] nb_l  = left_lbl;

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
    wire [LW-1:0] min_nb = min4(nb_ul, nb_t, nb_ur, nb_l);
    wire fg = bin_bram[scan];
    // label_bram 写数据（组合逻辑，供独立写块使用）
    wire [LW-1:0] label_wdata = fg ? (min_nb == {LW{1'b0}} ? (n_lbl < MAX_COMP - 1 ? n_lbl + 1'b1 : {LW{1'b0}}) : min_nb) : {LW{1'b0}};

    // 根标签：parent 已压缩后 parent[l-1] 即根
    wire [LW-1:0] lbl = label_bram[scan];
    wire [LW-1:0] root_lbl = (lbl != 0) ? parent[lbl-1] : {LW{1'b0}};

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

    // 有效组件数（组合逻辑计数，避免 NBA 循环累加 bug）
    reg [7:0] n_comp_c;
    always @* begin
        n_comp_c = 8'd0;
        for (i = 0; i < MAX_COMP; i = i + 1) begin
            if (carea[i] >= MIN_AREA && carea[i] <= MAX_AREA)
                n_comp_c = n_comp_c + 8'd1;
        end
    end

    reg [3:0] si;
    reg [6:0] sj;          // 需能计到 MAX_COMP（64）
    reg [5:0] mi;          // 0..MAX_COMP-1
    reg [7:0] maxp;
    reg [1:0] sort_phase;

    reg [7:0] o_data_r;
    reg o_valid_r;

    // ---- RAM 独立写块（标准 1写1读，供综合器推断 BRAM）----
    // bin_bram：写 + bin_cnt 递增/回绕
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) bin_cnt <= 0;
        else if (state == S_LOAD && i_bin_valid && !bin_loaded) begin
            bin_bram[bin_cnt] <= i_bin;
            if (bin_cnt == N - 1) bin_cnt <= 0;
            else bin_cnt <= bin_cnt + 1;
        end
    end
    // enh_bram：写 + enh_cnt 递增/回绕
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) enh_cnt <= 0;
        else if (state == S_LOAD && i_enh_valid && !enh_loaded) begin
            enh_bram[enh_cnt] <= i_enh;
            if (enh_cnt == N - 1) enh_cnt <= 0;
            else enh_cnt <= enh_cnt + 1;
        end
    end
    // label_bram：写 + scan 递增/回绕（S_LABEL 写标签，S_ACCUM 只扫描，S_UNION 回绕到 0）
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) scan <= 0;
        else if (state == S_LABEL && scan < N) begin
            label_bram[scan] <= label_wdata;
            scan <= scan + 1;
        end else if (state == S_UNION) begin
            scan <= 0;
        end else if (state == S_ACCUM && scan < N) begin
            scan <= scan + 1;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i < W; i = i + 1) prev_lbl[i] <= 0;
            for (i = 0; i < MAX_COMP; i = i + 1) begin parent[i] <= i + 1; carea[i] <= 0; csumx[i] <= 0; csumy[i] <= 0; cpeak[i] <= 0; cx[i] <= 0; cy[i] <= 0; end
            left_lbl <= 0; n_lbl <= 0; n_comp <= 0;
            col <= 0; row <= 0; cnt <= 0; ucnt <= 0;
            bin_loaded <= 0; enh_loaded <= 0;
            state <= S_LOAD;
            o_data_r <= 0; o_valid_r <= 0;
        end else begin
            o_valid_r <= 1'b0;
            case (state)
            S_LOAD: begin
                if (i_bin_valid && !bin_loaded && bin_cnt == N - 1) bin_loaded <= 1'b1;
                if (i_enh_valid && !enh_loaded && enh_cnt == N - 1) enh_loaded <= 1'b1;
                if (bin_loaded && enh_loaded) begin state <= S_LABEL; col <= 0; end
            end
            S_LABEL: begin
                if (scan < N) begin
                    if (fg) begin
                        if (min_nb == 0) begin
                            if (n_lbl < MAX_COMP - 1) begin
                                left_lbl <= n_lbl + 1;
                                prev_lbl[col] <= n_lbl + 1;
                                n_lbl <= n_lbl + 1;
                            end else begin left_lbl <= 0; prev_lbl[col] <= 0; end
                        end else begin
                            left_lbl <= min_nb;
                            prev_lbl[col] <= min_nb;
                            if (nb_ul != 0 && nb_ul != min_nb) parent[nb_ul-1] <= min_nb;
                            if (nb_t  != 0 && nb_t  != min_nb) parent[nb_t -1] <= min_nb;
                            if (nb_ur != 0 && nb_ur != min_nb) parent[nb_ur-1] <= min_nb;
                            if (nb_l  != 0 && nb_l  != min_nb) parent[nb_l -1] <= min_nb;
                        end
                    end else begin
                        left_lbl <= 0;
                        prev_lbl[col] <= 0;
                    end
                    if (col == W - 1) begin col <= 0; left_lbl <= 0; end
                    else col <= col + 1;
                end else begin
                    state <= S_UNION; ucnt <= 0;
                end
            end
            S_UNION: begin
                // 路径减半：parent[i] = parent[parent[i]-1]
                for (i = 0; i < MAX_COMP; i = i + 1) begin
                    if (parent[i] != 0 && parent[i] != i + 1)
                        parent[i] <= parent[parent[i]-1];
                end
                if (ucnt >= MAX_COMP) begin
                    state <= S_ACCUM; col <= 0; row <= 0;
                    for (i = 0; i < MAX_COMP; i = i + 1) begin carea[i] <= 0; csumx[i] <= 0; csumy[i] <= 0; cpeak[i] <= 0; end
                end else ucnt <= ucnt + 1;
            end
            S_ACCUM: begin
                if (scan < N) begin
                    if (bin_bram[scan] && root_lbl != 0) begin
                        carea[root_lbl-1] <= carea[root_lbl-1] + 16'd1;
                        csumx[root_lbl-1] <= csumx[root_lbl-1] + col;
                        csumy[root_lbl-1] <= csumy[root_lbl-1] + row;
                        if (enh_bram[scan] > cpeak[root_lbl-1]) cpeak[root_lbl-1] <= enh_bram[scan];
                    end
                    if (col == W - 1) begin col <= 0; row <= row + 1; end
                    else col <= col + 1;
                end else begin
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
            end
            S_SORT: begin
                if (sort_phase == 2'd0) begin
                    sj <= si; mi <= si; maxp <= cpeak[si];
                    sort_phase <= 2'd1;
                end else if (sort_phase == 2'd1) begin
                    if (sj < MAX_COMP) begin
                        if (cpeak[sj] > maxp) begin maxp <= cpeak[sj]; mi <= sj; end
                        sj <= sj + 4'd1;
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
                    else cnt <= cnt + 1;
                end
            end
            S_DONE: state <= S_DONE;
            endcase
        end
    end

    assign o_data  = o_data_r;
    assign o_valid = o_valid_r;
endmodule
