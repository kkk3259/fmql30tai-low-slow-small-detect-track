// tb_tophat.v —— Top-Hat 子模块测试平台
`timescale 1ns/1ps
module tb_tophat;
    reg clk, rst_n;
    reg [7:0] i_data;
    reg i_valid;
    wire [7:0] o_data;
    wire o_valid;
    reg o_ready;

    reg [7:0] in_mem [0:1023];

    tophat_5x5 #(.W(32), .H(32)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid),
        .o_data(o_data), .o_valid(o_valid), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file;

    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        $dumpfile("tb_tophat.vcd");
        $dumpvars(0, tb_tophat);

        $readmemh("input_gray.hex", in_mem);

        rst_n = 0; i_valid = 0; o_ready = 1;
        repeat (2) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        for (idx = 0; idx < 1024; idx = idx + 1) begin
            i_data = in_mem[idx];
            i_valid = 1'b1;
            @(posedge clk);
        end
        i_valid = 1'b0;

        out_idx = 0;
        out_file = $fopen("output_tophat.hex", "w");
        while (out_idx < 1024) begin
            @(posedge clk);
            if (o_valid) begin
                $fwrite(out_file, "%02X\n", o_data);
                out_idx = out_idx + 1;
            end
        end
        $fclose(out_file);
        $display("收集到 %0d 个输出像素", out_idx);
        #50 $finish;
    end
endmodule
