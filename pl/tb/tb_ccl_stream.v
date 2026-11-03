// tb_ccl_stream.v —— 流式候选提取(CCL)测试平台（64x64）
`timescale 1ns/1ps
module tb_ccl_stream;
    reg clk, rst_n;
    reg i_bin;
    reg [7:0] i_enh;
    reg bin_valid, enh_valid;
    wire o_valid;
    wire [7:0] o_data;
    reg o_ready;

    reg [7:0] bin_mem [0:4095];
    reg [7:0] enh_mem [0:4095];

    candidate_extract_stream #(.W(64), .H(64)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_bin(i_bin), .i_bin_valid(bin_valid),
        .i_enh(i_enh), .i_enh_valid(enh_valid),
        .o_valid(o_valid), .o_data(o_data), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file, idle;

    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        if ($fopen("input_bin.hex","r") == 0) begin $display("ERROR: 缺 input_bin.hex"); $finish; end
        if ($fopen("input_enh.hex","r") == 0) begin $display("ERROR: 缺 input_enh.hex"); $finish; end
        $readmemh("input_bin.hex", bin_mem);
        $readmemh("input_enh.hex", enh_mem);

        rst_n = 0; bin_valid = 0; enh_valid = 0; o_ready = 1;
        repeat (2) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        // 并行加载 bin + enh（独立 valid，同时给；negedge 更新避免与 DUT 的 posedge 采样竞争）
        for (idx = 0; idx < 4096; idx = idx + 1) begin
            i_bin = (bin_mem[idx] > 0) ? 1'b1 : 1'b0;
            i_enh = enh_mem[idx];
            bin_valid = 1'b1;
            enh_valid = 1'b1;
            @(negedge clk);
        end
        // 帧尾续喂零像素：CCL 内部的 3×3 去噪有 W+2 拍延迟，不补这一段
        // 最后两行的像素永远出不来，px_cnt 到不了 N-1，状态机不会进 S_MERGE。
        for (idx = 0; idx < 256; idx = idx + 1) begin
            i_bin = 1'b0;
            i_enh = 8'd0;
            bin_valid = 1'b1;
            enh_valid = 1'b1;
            @(negedge clk);
        end
        @(negedge clk);
        bin_valid = 1'b0;
        enh_valid = 1'b0;

        // 收集 36 字节输出
        out_idx = 0; idle = 0;
        out_file = $fopen("output_ccl_stream.hex", "w");
        while (out_idx < 36) begin
            @(posedge clk);
            if (o_valid) begin
                $fwrite(out_file, "%02X\n", o_data);
                out_idx = out_idx + 1;
                idle = 0;
            end else begin
                idle = idle + 1;
                if (idle > 2000000) begin $display("WATCHDOG out_idx=%0d", out_idx); $finish; end
            end
        end
        $fclose(out_file);
        $display("CCL 收集到 %0d 个输出", out_idx);
        #50 $finish;
    end
endmodule
