// tb_ip2_stream.v —— IP2 流式全链测试（128x72）
`timescale 1ns/1ps
module tb_ip2_stream;
    reg clk, rst_n;
    reg [7:0] i_data;
    reg i_valid;
    wire [7:0] o_data;
    wire o_valid;
    reg o_ready;

    reg [7:0] in_mem [0:9215];   // 128*72

    ip2_top_stream #(.W(128), .H(72)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid),
        .o_data(o_data), .o_valid(o_valid), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file, idle;

    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        if ($fopen("input_integration.hex","r") == 0) begin
            $display("ERROR: 缺 input_integration.hex，请先运行 pl/tools/gen_integration.py");
            $finish;
        end
        $readmemh("input_integration.hex", in_mem);

        rst_n = 0; i_valid = 0; o_ready = 1;
        repeat (2) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        for (idx = 0; idx < 9216; idx = idx + 1) begin
            i_data = in_mem[idx];
            i_valid = 1'b1;
            @(posedge clk);
        end
        @(posedge clk);
        i_valid = 1'b0;

        out_idx = 0; idle = 0;
        out_file = $fopen("output_integration_stream.hex", "w");
        while (out_idx < 36) begin
            @(posedge clk);
            if (o_valid) begin
                $fwrite(out_file, "%02X\n", o_data);
                out_idx = out_idx + 1;
                idle = 0;
            end else begin
                idle = idle + 1;
                if (idle > 20000000) begin $display("WATCHDOG out_idx=%0d", out_idx); $finish; end
            end
        end
        $fclose(out_file);
        $display("IP2 流式全链收集到 %0d 个输出", out_idx);
        #50 $finish;
    end
endmodule
