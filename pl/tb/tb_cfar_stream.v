// tb_cfar_stream.v —— 流式 CFAR 测试（64x64）
`timescale 1ns/1ps
module tb_cfar_stream;
    reg clk, rst_n;
    reg [7:0] i_data;
    reg i_valid;
    wire i_ready;
    wire [7:0] o_data;
    wire [7:0] o_enh;
    wire o_valid;
    reg o_ready;

    reg [7:0] in_mem [0:4095];

    cfar_threshold_stream #(.W(64), .H(64)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid), .i_ready(i_ready),
        .o_data(o_data), .o_enh(o_enh), .o_valid(o_valid), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file, idle;

    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        if ($fopen("input_cfar.hex","r") == 0) begin
            $display("ERROR: 缺 input_cfar.hex，请先运行 pl/tools/gen_cfar_stimulus.py");
            $finish;
        end
        $readmemh("input_cfar.hex", in_mem);

        rst_n = 0; i_valid = 0; o_ready = 1;
        repeat (2) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        // 加载阶段：i_ready 高时喂数据
        idx = 0;
        while (idx < 4096) begin
            @(posedge clk);
            if (i_ready) begin
                i_data = in_mem[idx];
                i_valid = 1'b1;
                idx = idx + 1;
            end
        end
        @(posedge clk);   // 多等一拍，让模块处理最后一个像素
        i_valid = 1'b0;

        // 收集输出（S_MAD 阶段）
        out_idx = 0; idle = 0;
        out_file = $fopen("output_cfar_stream.hex", "w");
        while (out_idx < 4096) begin
            @(posedge clk);
            if (o_valid) begin
                $fwrite(out_file, "%02X\n", o_data);
                out_idx = out_idx + 1;
                idle = 0;
            end else begin
                idle = idle + 1;
                if (idle > 1000000) begin $display("WATCHDOG out_idx=%0d", out_idx); $finish; end
            end
        end
        $fclose(out_file);
        $display("流式 CFAR 收集到 %0d 个输出像素", out_idx);
        #50 $finish;
    end
endmodule
