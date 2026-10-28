// ============================================================================
// minmax_tree.v —— 平衡树形归约（求 N 个 8 位数据的最小值或最大值）
//
// 为什么需要它：直接写 hc[i] = min(hc[i-1], tap[i]) 是“线性链”，
// 21×21=441 个抽头串起来有 441 级比较（实测综合后 60 级逻辑、WNS -7.775 ns @50MHz）。
// 改成每级两两归约的平衡树，深度降到 log2(N)：
//   441 → 每行 21 个（深度 5）→ 21 个行结果再归约（深度 5）→ 共 10 级。
//
// 用法：din 是 N*W 位的扁平向量（din[(i+1)*W-1 -: W] 是第 i 个数）
// ============================================================================
module minmax_tree #(
    parameter N      = 21,          // 元素个数
    parameter W      = 8,           // 每个元素位宽
    parameter IS_MAX = 0            // 0=求最小（腐蚀/erode），1=求最大（膨胀/dilate）
) (
    input  wire [N*W-1:0] din,
    output wire [W-1:0]   dout
);

    // 每级宽度（向上取整的一半），最多支持 N ≤ 64
    localparam N1 = (N  + 1) / 2;
    localparam N2 = (N1 + 1) / 2;
    localparam N3 = (N2 + 1) / 2;
    localparam N4 = (N3 + 1) / 2;
    localparam N5 = (N4 + 1) / 2;
    localparam N6 = (N5 + 1) / 2;

    wire [N1*W-1:0] s1;
    wire [N2*W-1:0] s2;
    wire [N3*W-1:0] s3;
    wire [N4*W-1:0] s4;
    wire [N5*W-1:0] s5;
    wire [N6*W-1:0] s6;

    genvar i;
    generate
        // --- 第 1 级：从 din 归约 ---
        for (i = 0; i < N1; i = i + 1) begin : g_s1
            if (2*i + 1 < N) begin : g_pair
                if (IS_MAX) begin : g_max
                    assign s1[i*W +: W] = (din[(2*i)*W +: W] > din[(2*i+1)*W +: W]) ?
                                          din[(2*i)*W +: W] : din[(2*i+1)*W +: W];
                end else begin : g_min
                    assign s1[i*W +: W] = (din[(2*i)*W +: W] < din[(2*i+1)*W +: W]) ?
                                          din[(2*i)*W +: W] : din[(2*i+1)*W +: W];
                end
            end else begin : g_single
                assign s1[i*W +: W] = din[(2*i)*W +: W];
            end
        end

        // --- 第 2 级 ---
        for (i = 0; i < N2; i = i + 1) begin : g_s2
            if (2*i + 1 < N1) begin : g_pair
                if (IS_MAX) begin : g_max
                    assign s2[i*W +: W] = (s1[(2*i)*W +: W] > s1[(2*i+1)*W +: W]) ?
                                          s1[(2*i)*W +: W] : s1[(2*i+1)*W +: W];
                end else begin : g_min
                    assign s2[i*W +: W] = (s1[(2*i)*W +: W] < s1[(2*i+1)*W +: W]) ?
                                          s1[(2*i)*W +: W] : s1[(2*i+1)*W +: W];
                end
            end else begin : g_single
                assign s2[i*W +: W] = s1[(2*i)*W +: W];
            end
        end

        // --- 第 3 级 ---
        for (i = 0; i < N3; i = i + 1) begin : g_s3
            if (2*i + 1 < N2) begin : g_pair
                if (IS_MAX) begin : g_max
                    assign s3[i*W +: W] = (s2[(2*i)*W +: W] > s2[(2*i+1)*W +: W]) ?
                                          s2[(2*i)*W +: W] : s2[(2*i+1)*W +: W];
                end else begin : g_min
                    assign s3[i*W +: W] = (s2[(2*i)*W +: W] < s2[(2*i+1)*W +: W]) ?
                                          s2[(2*i)*W +: W] : s2[(2*i+1)*W +: W];
                end
            end else begin : g_single
                assign s3[i*W +: W] = s2[(2*i)*W +: W];
            end
        end

        // --- 第 4 级 ---
        for (i = 0; i < N4; i = i + 1) begin : g_s4
            if (2*i + 1 < N3) begin : g_pair
                if (IS_MAX) begin : g_max
                    assign s4[i*W +: W] = (s3[(2*i)*W +: W] > s3[(2*i+1)*W +: W]) ?
                                          s3[(2*i)*W +: W] : s3[(2*i+1)*W +: W];
                end else begin : g_min
                    assign s4[i*W +: W] = (s3[(2*i)*W +: W] < s3[(2*i+1)*W +: W]) ?
                                          s3[(2*i)*W +: W] : s3[(2*i+1)*W +: W];
                end
            end else begin : g_single
                assign s4[i*W +: W] = s3[(2*i)*W +: W];
            end
        end

        // --- 第 5 级 ---
        for (i = 0; i < N5; i = i + 1) begin : g_s5
            if (2*i + 1 < N4) begin : g_pair
                if (IS_MAX) begin : g_max
                    assign s5[i*W +: W] = (s4[(2*i)*W +: W] > s4[(2*i+1)*W +: W]) ?
                                          s4[(2*i)*W +: W] : s4[(2*i+1)*W +: W];
                end else begin : g_min
                    assign s5[i*W +: W] = (s4[(2*i)*W +: W] < s4[(2*i+1)*W +: W]) ?
                                          s4[(2*i)*W +: W] : s4[(2*i+1)*W +: W];
                end
            end else begin : g_single
                assign s5[i*W +: W] = s4[(2*i)*W +: W];
            end
        end

        // --- 第 6 级 ---
        for (i = 0; i < N6; i = i + 1) begin : g_s6
            if (2*i + 1 < N5) begin : g_pair
                if (IS_MAX) begin : g_max
                    assign s6[i*W +: W] = (s5[(2*i)*W +: W] > s5[(2*i+1)*W +: W]) ?
                                          s5[(2*i)*W +: W] : s5[(2*i+1)*W +: W];
                end else begin : g_min
                    assign s6[i*W +: W] = (s5[(2*i)*W +: W] < s5[(2*i+1)*W +: W]) ?
                                          s5[(2*i)*W +: W] : s5[(2*i+1)*W +: W];
                end
            end else begin : g_single
                assign s6[i*W +: W] = s5[(2*i)*W +: W];
            end
        end

        // --- 结果：取最先收敛到 1 个元素的那一级 ---
        if (N1 == 1) begin : g_out1
            assign dout = s1[W-1:0];
        end else if (N2 == 1) begin : g_out2
            assign dout = s2[W-1:0];
        end else if (N3 == 1) begin : g_out3
            assign dout = s3[W-1:0];
        end else if (N4 == 1) begin : g_out4
            assign dout = s4[W-1:0];
        end else if (N5 == 1) begin : g_out5
            assign dout = s5[W-1:0];
        end else begin : g_out6
            assign dout = s6[W-1:0];
        end
    endgenerate

endmodule
