// postproc_axis.v —— IP3 后处理：坐标变换(×2 换回原图坐标) + NMS(合并过近候选)
// 输入：候选列表（33 字节：n_cand + 8×(x,y,area,peak)，降采样坐标，已按 peak 降序）
// 输出：候选列表（33 字节，x/y ×2 到原图坐标；NMS 抑制与更高 peak 候选过近者，空槽补 0）
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
    localparam NW = 33;

    reg [7:0] in_list  [0:NW-1];
    reg [7:0] out_list [0:NW-1];

    reg [5:0] cnt;
    reg [1:0] state;
    localparam S_IN = 2'd0, S_PROC = 2'd1, S_OUT = 2'd2, S_DONE = 2'd3;

    // ---- 组合逻辑：×2 + NMS + 压缩 ----
    reg [7:0] xx [0:MAX_CAND-1];
    reg [7:0] yy [0:MAX_CAND-1];
    reg [0:0] keep [0:MAX_CAND-1];
    reg [7:0] n_out;
    reg [7:0] dx, dy;
    reg suppressed;
    integer i, j, p, cntv;
    always @* begin
        // 1) ×2 坐标
        for (i = 0; i < MAX_CAND; i = i + 1) begin
            xx[i] = in_list[1 + i*4 + 0] << 1;
            yy[i] = in_list[1 + i*4 + 1] << 1;
        end
        // 2) NMS：keep[i]=1 表示保留（不与前面更高 peak 的候选过近）
        for (i = 0; i < MAX_CAND; i = i + 1) keep[i] = 1'b0;
        cntv = 0;
        for (i = 0; i < in_list[0] && i < MAX_CAND; i = i + 1) begin
            suppressed = 1'b0;
            for (j = 0; j < i; j = j + 1) begin
                if (keep[j]) begin
                    dx = (xx[i] >= xx[j]) ? (xx[i] - xx[j]) : (xx[j] - xx[i]);
                    dy = (yy[i] >= yy[j]) ? (yy[i] - yy[j]) : (yy[j] - yy[i]);
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
        // 3) 输出组装（按 keep 顺序压缩）
        out_list[0] = n_out;
        for (i = 1; i < NW; i = i + 1) out_list[i] = 8'd0;
        p = 0;
        for (i = 0; i < in_list[0] && i < MAX_CAND; i = i + 1) begin
            if (keep[i] && p < MAX_CAND) begin
                out_list[1 + p*4 + 0] = xx[i];
                out_list[1 + p*4 + 1] = yy[i];
                out_list[1 + p*4 + 2] = in_list[1 + i*4 + 2];   // area 不变
                out_list[1 + p*4 + 3] = in_list[1 + i*4 + 3];   // peak 不变
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
