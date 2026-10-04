// tb_tophat_stream.v —— 流式 5x5 Top-Hat 测试（32x32）
`timescale 1ns/1ps
module tb_tophat_stream;
    reg clk, rst_n;
    reg [7:0] i_data;
    reg i_valid;
    wire i_ready;
    wire [7:0] o_data;
    wire o_valid;
    reg o_ready;

    reg [7:0] in_mem [0:1023];   // 32*32

    tophat_5x5_stream #(.W(32), .H(32)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid), .i_ready(i_ready),
        .o_data(o_data), .o_valid(o_valid), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file, idle;

    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        if ($fopen("input_gray.hex","r") == 0) begin
            $display("ERROR: 缺 input_gray.hex，请先运行 pl/tools/gen_ip2_stimulus.py");
            $finish;
        end
        $readmemh("input_gray.hex", in_mem);

        rst_n = 0; i_valid = 0; o_ready = 1;
        repeat (2) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        out_idx = 0; idle = 0; idx = 0;
        out_file = $fopen("output_tophat_stream.hex", "w");
        while (out_idx < 1024) begin
            @(posedge clk);
            // 边喂边收（流式有延迟，输出与输入并发）
            if (idx < 1024) begin
                i_data = in_mem[idx];
                i_valid = 1'b1;
                idx = idx + 1;
            end else begin
                i_valid = 1'b0;
            end
            if (o_valid) begin
                $fwrite(out_file, "%02X\n", o_data);
                if (out_idx < 5) $display("DBG 收集 #%0d: o_data=%h @t=%0t", out_idx, o_data, $time);
                out_idx = out_idx + 1;
                idle = 0;
            end else begin
                idle = idle + 1;
                if (idle > 100000) begin $display("WATCHDOG out_idx=%0d", out_idx); $finish; end
            end
        end
        $fclose(out_file);
        $display("流式 Top-Hat 收集到 %0d 个输出像素", out_idx);
        #50 $finish;
    end
endmodule
