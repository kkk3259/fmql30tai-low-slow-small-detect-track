// postproc_axis.v —— IP3 后处理：坐标变换(×2 换回原图坐标) + NMS(合并过近候选)
// 输入/输出：57 字节候选列表（n_cand + 8×(x_hi,x_lo,y_hi,y_lo,area_hi,area_lo,peak)）
// 输入为降采样坐标，输出 x/y 已 ×2 到原图坐标；NMS 抑制过近的低 peak 候选
module postproc_axis #(
    parameter MAX_CAND = 8,
    parameter NMS_DIST = 6      // 合并距离阈值（原图坐标，像素）
)(
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] i_data,
    input  wire i_valid,
    output reg  [7:0] o_data,
    output reg  o_valid,
    input  wire o_ready
);
    localparam NW = 57;

    reg [7:0] in_list  [0:NW-1];
    reg [7:0] out_list [0:NW-1];

    reg [5:0] cnt;
    reg [1:0] state;
    localparam S_IN = 2'd0, S_PROC = 2'd1, S_OUT = 2'd2, S_DONE = 2'd3;

    // ---- 组合逻辑：解析 16 位 + ×2 + NMS + 压缩 ----
    reg [15:0] x16 [0:MAX_CAND-1];
    reg [15:0] y16 [0:MAX_CAND-1];
    reg [15:0] x2  [0:MAX_CAND-1];
    reg [15:0] y2  [0:MAX_CAND-1];
    reg [0:0]  keep [0:MAX_CAND-1];
    reg [7:0]  n_out;
    reg [15:0] dx, dy;
    reg suppressed;
    integer i, j, p, cntv;
    always @* begin
        // 1) 解析 16 位坐标 + ×2
        for (i = 0; i < MAX_CAND; i = i + 1) begin
            x16[i] = (in_list[1 + i*7 + 0] << 8) | in_list[1 + i*7 + 1];
            y16[i] = (in_list[1 + i*7 + 2] << 8) | in_list[1 + i*7 + 3];
            x2[i]  = x16[i] << 1;
            y2[i]  = y16[i] << 1;
        end
        // 2) NMS：keep[i]=1 表示保留
        for (i = 0; i < MAX_CAND; i = i + 1) keep[i] = 1'b0;
        cntv = 0;
        for (i = 0; i < in_list[0] && i < MAX_CAND; i = i + 1) begin
            suppressed = 1'b0;
            for (j = 0; j < i; j = j + 1) begin
                if (keep[j]) begin
                    dx = (x2[i] >= x2[j]) ? (x2[i] - x2[j]) : (x2[j] - x2[i]);
                    dy = (y2[i] >= y2[j]) ? (y2[i] - y2[j]) : (y2[j] - y2[i]);
                    if (dx <= NMS_DIST && dy <= NMS_DIST)
                        suppressed = 1'b1;
                end
            end
            if (!suppressed) begin
                keep[i] = 1'b1;
                cntv = cntv + 1;
            end
        end
        n_out = cntv;
        // 3) 组装 57 字节输出
        out_list[0] = n_out;
        for (i = 1; i < NW; i = i + 1) out_list[i] = 8'd0;
        p = 0;
        for (i = 0; i < in_list[0] && i < MAX_CAND; i = i + 1) begin
            if (keep[i] && p < MAX_CAND) begin
                out_list[1 + p*7 + 0] = x2[i][15:8];
                out_list[1 + p*7 + 1] = x2[i][7:0];
                out_list[1 + p*7 + 2] = y2[i][15:8];
                out_list[1 + p*7 + 3] = y2[i][7:0];
                out_list[1 + p*7 + 4] = 8'd0;                       // area 高字节
                out_list[1 + p*7 + 5] = in_list[1 + i*7 + 5];       // area 低字节
                out_list[1 + p*7 + 6] = in_list[1 + i*7 + 6];       // peak
                p = p + 1;
            end
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 6'd0; state <= S_IN; o_data <= 8'd0; o_valid <= 1'b0;
        end else begin
            case (state)
                S_IN: begin
                    if (i_valid) begin
                        in_list[cnt[5:0]] <= i_data;
                        if (cnt == NW - 1) begin state <= S_PROC; cnt <= 6'd0; end
                        else cnt <= cnt + 6'd1;
                    end
                end
                S_PROC: state <= S_OUT;
                S_OUT: begin
                    o_data  <= out_list[cnt[5:0]];
                    o_valid <= 1'b1;
                    if (o_ready) begin
                        if (cnt == NW - 1) state <= S_DONE;
                        else cnt <= cnt + 6'd1;
                    end
                end
                S_DONE: o_valid <= 1'b0;
            endcase
        end
    end
endmodule
