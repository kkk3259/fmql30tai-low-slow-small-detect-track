// ============================================================================
// ip2_pattern_gen.v —— 片上自测图案发生器（带 ready/valid 握手）
//
// 图案（按分辨率等比缩放，便于 128x72 仿真 / 640x360 上板共用一套逻辑）：
//   · 背景 = 8 + x 的高 4 位  →  8..23 的水平灰阶渐变（有纹理，不是纯色）
//   · 4 个 3x3 亮点（值 240）→ 面积 9，落在 CCL 的 [MIN_AREA,MAX_AREA]=[2,200] 内，
//     期望被 Top-Hat + CFAR + CCL 检出为 4 个候选
//   · 1 个 (W/8 x W/8) 大亮块（值 200）→ 面积远超 MAX_AREA，期望被面积门限滤掉，
//     用来在硬件上验证"大目标不误检"
//
// 握手：o_valid 常高表示"有像素"，x/y 只在 (o_valid && i_ready) 时推进；
//       末像素被接收的那一拍打出 frame_done。
//       o_data 组合来自当前 (x,y)，因此推进后下一拍自动是新像素。
// ============================================================================
module ip2_pattern_gen #(
    parameter W = 640,
    parameter H = 360
)(
    input  wire       clk,
    input  wire       rst_n,
    input  wire       en,          // 1 = 允许出一帧
    input  wire       i_ready,     // 下游可接收
    output wire [7:0] o_data,
    output reg        o_valid,
    output reg        frame_done   // 末像素被接收时打一拍
);
    localparam CW = (W <= 2) ? 1 : $clog2(W);
    localparam CH = (H <= 2) ? 1 : $clog2(H);

    // ---- 亮点/大块位置（整数常量，编译期算好）----
    localparam integer BX0 = W / 6;        // 左上亮点
    localparam integer BY0 = H / 5;
    localparam integer BX1 = W / 2;        // 右上亮点
    localparam integer BY1 = H / 5;
    localparam integer BX2 = W / 6;        // 左下亮点
    localparam integer BY2 = (H * 3) / 5;
    localparam integer BX3 = W / 2;        // 右下亮点
    localparam integer BY3 = (H * 3) / 5;
    localparam integer KX  = (W * 3) / 4;  // 大块中心
    localparam integer KY  = H / 2;
    localparam integer KS  = W / 16;       // 大块半宽 → 边长 W/8

    reg [CW-1:0] x;
    reg [CH-1:0] y;
    reg          run;

    wire [CW-1:0] xu = x;
    wire [CH-1:0] yu = y;

    // ---- 背景渐变：8 + (x >> (CW-4))，即 0..15 ----
    wire [7:0] bg = 8'd8 + {4'd0, x[CW-1 -: 4]};

    // ---- 4 个 3x3 亮点 ----
    wire d0 = (xu >= BX0-1) && (xu <= BX0+1) && (yu >= BY0-1) && (yu <= BY0+1);
    wire d1 = (xu >= BX1-1) && (xu <= BX1+1) && (yu >= BY1-1) && (yu <= BY1+1);
    wire d2 = (xu >= BX2-1) && (xu <= BX2+1) && (yu >= BY2-1) && (yu <= BY2+1);
    wire d3 = (xu >= BX3-1) && (xu <= BX3+1) && (yu >= BY3-1) && (yu <= BY3+1);
    wire in_dot = d0 | d1 | d2 | d3;

    // ---- 1 个大亮块（期望被面积门限滤掉）----
    wire in_big = (xu >= KX-KS) && (xu <= KX+KS) && (yu >= KY-KS) && (yu <= KY+KS);

    assign o_data = in_dot ? 8'd240 : (in_big ? 8'd200 : bg);

    wire hs = o_valid & i_ready;

    always @(posedge clk) begin
        if (!rst_n) begin
            x <= {CW{1'b0}};
            y <= {CH{1'b0}};
            run <= 1'b0;
            o_valid <= 1'b0;
            frame_done <= 1'b0;
        end else begin
            frame_done <= 1'b0;   // 默认清零，只在末像素那拍置 1
            if (!run) begin
                x <= {CW{1'b0}};
                y <= {CH{1'b0}};
                o_valid <= 1'b0;
                if (en) begin
                    run <= 1'b1;
                    o_valid <= 1'b1;
                end
            end else if (hs) begin
                if (xu == W - 1) begin
                    x <= {CW{1'b0}};
                    if (yu == H - 1) begin
                        run <= 1'b0;
                        o_valid <= 1'b0;
                        y <= {CH{1'b0}};
                        frame_done <= 1'b1;
                    end else begin
                        y <= yu + 1'b1;
                    end
                end else begin
                    x <= xu + 1'b1;
                end
            end
        end
    end

endmodule
