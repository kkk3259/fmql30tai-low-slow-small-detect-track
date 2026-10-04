// tb_ip2_top_320.v —— IP2 全链 320x180 真实分辨率测试（宽 320 验证 16 位坐标）
`timescale 1ns/1ps
module tb_ip2_top_320;
    reg clk, rst_n;
    reg [7:0] i_data;
    reg i_valid;
    wire [7:0] o_data;
    wire o_valid;
    reg o_ready;

    reg [7:0] in_mem [0:57599];   // 320*180

    ip2_top #(.W(320), .H(180)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid),
        .o_data(o_data), .o_valid(o_valid), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file, idle;

    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        $dumpfile("tb_ip2_top_320.vcd");
        $dumpvars(0, tb_ip2_top_320);
        if ($fopen("input_integration_320.hex","r") == 0) begin
            $display("ERROR: 缺 input_integration_320.hex，请先运行 pl/tools/gen_integration_320.py");
            $finish;
        end
        $readmemh("input_integration_320.hex", in_mem);

        rst_n = 0; i_valid = 0; o_ready = 1;
        repeat (2) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        for (idx = 0; idx < 57600; idx = idx + 1) begin
            i_data = in_mem[idx];
            i_valid = 1'b1;
            @(posedge clk);
        end
        i_valid = 1'b0;

        out_idx = 0; idle = 0;
        out_file = $fopen("output_integration_320.hex", "w");
        while (out_idx < 57) begin
            @(posedge clk);
            if (o_valid) begin
                $fwrite(out_file, "%02X\n", o_data);
                out_idx = out_idx + 1;
                idle = 0;
            end else begin
                idle = idle + 1;
                if (idle > 10000000) begin $display("WATCHDOG out_idx=%0d", out_idx); $finish; end
            end
        end
        $fclose(out_file);
        $display("320x180 全链收集到 %0d 个输出", out_idx);
        #50 $finish;
    end
endmodule
