// tb_preproc.v —— IP1 测试平台：读 input.hex 喂入，收集输出写 output.hex
`timescale 1ns/1ps
module tb_preproc;
    reg clk, rst_n;
    reg [7:0] i_r, i_g, i_b;
    reg i_valid;
    wire [7:0] o_data;
    wire o_valid;
    reg o_ready;

    reg [23:0] in_mem [0:1023];

    preproc_axis #(.W_IN(32), .H_IN(32)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_r(i_r), .i_g(i_g), .i_b(i_b), .i_valid(i_valid),
        .o_data(o_data), .o_valid(o_valid), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file;

    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        $dumpfile("tb_preproc.vcd");
        $dumpvars(0, tb_preproc);

        if ($fopen("input.hex","r") == 0) begin
            $display("ERROR: 缺 input.hex，请先运行 pl/tools/gen_stimulus.py");
            $finish;
        end
        $readmemh("input.hex", in_mem);

        rst_n = 0; i_valid = 0; o_ready = 1;
        repeat (2) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        // 喂入 1024 个 RGB 像素
        for (idx = 0; idx < 1024; idx = idx + 1) begin
            i_r = in_mem[idx][23:16];
            i_g = in_mem[idx][15:8];
            i_b = in_mem[idx][7:0];
            i_valid = 1'b1;
            @(posedge clk);
        end
        i_valid = 1'b0;

        // 收集 256 个输出像素
        out_idx = 0;
        out_file = $fopen("output.hex", "w");
        while (out_idx < 256) begin
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
