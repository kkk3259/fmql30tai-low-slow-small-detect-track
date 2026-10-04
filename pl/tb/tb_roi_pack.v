// tb_roi_pack.v —— IP4 roi_pack 测试（160x160，4 候选，各裁 128x128）
`timescale 1ns/1ps
module tb_roi_pack;
    reg clk, rst_n;
    reg [7:0] i_data;
    reg i_valid;
    wire [7:0] o_data;
    wire o_valid;
    reg o_ready;

    reg [7:0] gray_mem [0:25599];   // 160*160
    reg [7:0] cand_mem [0:35];      // 36 字节候选

    roi_pack #(.W(160), .H(160), .ROI(128)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid),
        .o_data(o_data), .o_valid(o_valid), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file, idle;
    integer n_cand, total_out;
    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        if ($fopen("input_roi_gray.hex","r") == 0) begin $display("ERROR: 缺 input_roi_gray.hex"); $finish; end
        if ($fopen("input_roi_cand.hex","r") == 0) begin $display("ERROR: 缺 input_roi_cand.hex"); $finish; end
        $readmemh("input_roi_gray.hex", gray_mem);
        $readmemh("input_roi_cand.hex", cand_mem);
        n_cand = cand_mem[0];
        total_out = n_cand * 16384;

        rst_n = 0; i_valid = 0; o_ready = 1;
        repeat (2) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        // 1) 喂灰度
        for (idx = 0; idx < 25600; idx = idx + 1) begin
            i_data = gray_mem[idx];
            i_valid = 1'b1;
            @(posedge clk);
        end
        i_valid = 1'b0;
        @(posedge clk);
        // 2) 喂候选
        for (idx = 0; idx < 36; idx = idx + 1) begin
            i_data = cand_mem[idx];
            i_valid = 1'b1;
            @(posedge clk);
        end
        i_valid = 1'b0;

        // 3) 收输出
        out_idx = 0; idle = 0;
        out_file = $fopen("output_roi.hex", "w");
        while (out_idx < total_out) begin
            @(posedge clk);
            if (o_valid) begin
                $fwrite(out_file, "%02X\n", o_data);
                out_idx = out_idx + 1;
                idle = 0;
            end else begin
                idle = idle + 1;
                if (idle > 200000) begin $display("WATCHDOG out_idx=%0d", out_idx); $finish; end
            end
        end
        $fclose(out_file);
        $display("roi_pack 收集到 %0d 字节（%0d 个候选 × 128×128）", out_idx, n_cand);
        #50 $finish;
    end
endmodule
