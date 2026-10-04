// candidate_extract.v —— IP2 子模块③：候选提取 v2（8 连通 CCL + 质心/面积/峰值）
// 输入二值图(bin) + 增强图(enh)，DFS 洪泛找连通域，输出 x/y/area/peak，按 peak 降序取前 MAX_CAND
module candidate_extract #(
    parameter W = 64,
    parameter H = 64,
    parameter MAX_CAND = 8,
    parameter MIN_AREA = 2,
    parameter MAX_AREA = 200,
    parameter MAX_COMP = 64
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] i_bin,
    input  wire i_bin_valid,
    input  wire [7:0] i_enh,
    input  wire i_enh_valid,
    output reg  o_valid,
    output reg  [7:0] o_data,
    input  wire o_ready
);
    localparam N  = W * H;
    localparam CW = $clog2(W);      // 列宽 = 6
    localparam CH = $clog2(H);      // 行宽 = 6
    localparam CNT_W = CW + CH;     // 12

    // 图像缓冲（2D，复位时不初始化，加载阶段会全部写满）
    reg [0:0] bin [0:H-1][0:W-1];
    reg [7:0] enh [0:H-1][0:W-1];
    // DFS 栈
    reg [CW-1:0] sx [0:N-1];
    reg [CH-1:0] sy [0:N-1];
    reg [15:0] sp;
    // 候选
    reg [CW-1:0] cx [0:MAX_COMP-1];
    reg [CH-1:0] cy [0:MAX_COMP-1];
    reg [15:0]   carea [0:MAX_COMP-1];
    reg [7:0]    cpeak [0:MAX_COMP-1];
    reg [7:0] n_comp;

    reg [3:0] state;
    localparam S_LOAD = 0, S_SCAN = 1, S_FILL = 2, S_SORT = 3, S_OUT = 4, S_DONE = 5;

    reg [CNT_W-1:0] bin_cnt, enh_cnt;
    reg bin_loaded, enh_loaded;
    reg [CNT_W-1:0] cnt;   // 输出计数
    reg [CNT_W:0] scan;    // 扫描指针（需 CNT_W+1 位到 N 才能终止）
    reg [3:0]  fstep;      // 洪泛子步：0=弹出累加, 1..8=查邻居, 9=收尾
    reg [CW-1:0] px;
    reg [CH-1:0] py;
    reg [15:0] x_sum, y_sum, area;
    reg [7:0]  peak;
    // 排序
    reg [3:0] si;
    reg [5:0] sj, mi;      // 需 6 位：候选数最多 MAX_COMP=64
    reg [7:0] maxp;
    reg [1:0] sort_phase;

    // ---- 8 邻居偏移（fstep-1 = 0..7）----
    reg signed [CW:0] ndx, ndy;
    always @* begin
        case (fstep - 4'd1)
            4'd0: begin ndx = -1; ndy = -1; end
            4'd1: begin ndx =  0; ndy = -1; end
            4'd2: begin ndx =  1; ndy = -1; end
            4'd3: begin ndx = -1; ndy =  0; end
            4'd4: begin ndx =  1; ndy =  0; end
            4'd5: begin ndx = -1; ndy =  1; end
            4'd6: begin ndx =  0; ndy =  1; end
            default: begin ndx = 1; ndy = 1; end
        endcase
    end

    wire signed [CW:0] nx_s = $signed({1'b0, px}) + ndx;
    wire signed [CH:0] ny_s = $signed({1'b0, py}) + ndy;
    wire inb  = (nx_s >= 0) && (nx_s < W) && (ny_s >= 0) && (ny_s < H);
    wire [CW-1:0] nxu = nx_s[CW-1:0];
    wire [CH-1:0] nyu = ny_s[CH-1:0];
    wire is_fg = inb && (bin[nyu][nxu] == 1'b1);

    // 栈顶像素（弹出时算 peak）
    wire [CH-1:0] top_y = sy[sp-1];
    wire [CW-1:0] top_x = sx[sp-1];

    // 输出字段选择（57 字节：n_cand + 8×(x_hi,x_lo,y_hi,y_lo,area_hi,area_lo,peak)，x/y/area 16 位）
    wire [5:0] out_idx = cnt[5:0];                  // 0..56
    wire [2:0] cand_i  = (out_idx - 7'd1) / 3'd7;   // 0..7
    wire [2:0] field   = (out_idx - 7'd1) % 3'd7;   // 0..6
    wire [15:0] x16 = {{(16-CW){1'b0}}, cx[cand_i]};
    wire [15:0] y16 = {{(16-CH){1'b0}}, cy[cand_i]};
    reg [7:0] out_val;
    always @* begin
        if (out_idx == 6'd0)
            out_val = (n_comp < MAX_CAND) ? n_comp : MAX_CAND[7:0];
        else if (cand_i >= n_comp)
            out_val = 8'd0;                          // 空槽补 0
        else begin
            case (field)
                3'd0: out_val = x16[15:8];
                3'd1: out_val = x16[7:0];
                3'd2: out_val = y16[15:8];
                3'd3: out_val = y16[7:0];
                3'd4: out_val = 8'd0;                // area 高字节恒 0
                3'd5: out_val = carea[cand_i][7:0];
                3'd6: out_val = cpeak[cand_i];
            endcase
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_LOAD; bin_cnt <= 0; enh_cnt <= 0; bin_loaded <= 1'b0; enh_loaded <= 1'b0;
            cnt <= 0; scan <= 0; o_valid <= 1'b0; o_data <= 8'd0;
            n_comp <= 8'd0; sp <= 16'd0; fstep <= 4'd0;
            si <= 4'd0; sj <= 4'd0; mi <= 4'd0; maxp <= 8'd0; sort_phase <= 2'd0;
        end else begin
            case (state)
                S_LOAD: begin
                    if (i_bin_valid && !bin_loaded) begin
                        bin[bin_cnt[CNT_W-1:CW]][bin_cnt[CW-1:0]] <= (i_bin > 0);
                        if (bin_cnt == N - 1) bin_loaded <= 1'b1;
                        else bin_cnt <= bin_cnt + 1;
                    end
                    if (i_enh_valid && !enh_loaded) begin
                        enh[enh_cnt[CNT_W-1:CW]][enh_cnt[CW-1:0]] <= i_enh;
                        if (enh_cnt == N - 1) enh_loaded <= 1'b1;
                        else enh_cnt <= enh_cnt + 1;
                    end
                    if (bin_loaded && enh_loaded) begin
                        state <= S_SCAN; scan <= 0;
                    end
                end
                S_SCAN: begin
                    if (scan < N) begin
                        if (bin[scan[CNT_W-1:CW]][scan[CW-1:0]] == 1'b1) begin
                            px <= scan[CW-1:0]; py <= scan[CNT_W-1:CW];
                            sx[0] <= scan[CW-1:0]; sy[0] <= scan[CNT_W-1:CW]; sp <= 16'd1;
                            bin[scan[CNT_W-1:CW]][scan[CW-1:0]] <= 1'b0;
                            x_sum <= 16'd0; y_sum <= 16'd0; area <= 16'd0; peak <= 8'd0;
                            fstep <= 4'd0;
                            state <= S_FILL;
                        end else begin
                            scan <= scan + 1;
                        end
                    end else begin
                        state <= S_SORT; si <= 4'd0; sort_phase <= 2'd0;
                    end
                end
                S_FILL: begin
                    if (fstep == 4'd0) begin
                        // 弹出栈顶并累加
                        x_sum <= x_sum + sx[sp-1];
                        y_sum <= y_sum + sy[sp-1];
                        area  <= area + 16'd1;
                        if (enh[top_y][top_x] > peak) peak <= enh[top_y][top_x];
                        px <= sx[sp-1]; py <= sy[sp-1];
                        sp <= sp - 16'd1;
                        fstep <= 4'd1;
                    end else if (fstep <= 4'd8) begin
                        // 检查第 (fstep-1) 个邻居
                        if (is_fg) begin
                            bin[nyu][nxu] <= 1'b0;
                            sx[sp] <= nxu; sy[sp] <= nyu;
                            sp <= sp + 16'd1;
                        end
                        fstep <= fstep + 4'd1;
                    end else begin
                        // 8 邻居查完，栈空则组件完成
                        if (sp == 16'd0) begin
                            if (area >= MIN_AREA && area <= MAX_AREA && n_comp < MAX_COMP) begin
                                cx[n_comp]    <= (x_sum + area / 16'd2) / area;
                                cy[n_comp]    <= (y_sum + area / 16'd2) / area;
                                carea[n_comp] <= area;
                                cpeak[n_comp] <= peak;
                                n_comp <= n_comp + 8'd1;
                            end
                            state <= S_SCAN;
                        end else begin
                            fstep <= 4'd0;
                        end
                    end
                end
                S_SORT: begin
                    // 选择排序：每轮把 peak 最大的换到 si 位置
                    if (sort_phase == 2'd0) begin
                        sj <= si; mi <= si; maxp <= cpeak[si];
                        sort_phase <= 2'd1;
                    end else if (sort_phase == 2'd1) begin
                        if (sj < n_comp) begin
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
                    o_valid <= 1'b1;
                    o_data  <= out_val;
                    if (o_ready) begin
                        if (out_idx == 6'd56) state <= S_DONE;
                        else cnt <= cnt + 1;
                    end
                end
                S_DONE: o_valid <= 1'b0;
            endcase
        end
    end
endmodule
