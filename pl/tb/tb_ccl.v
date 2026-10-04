// tb_ccl.v —— 候选提取(CCL v2)测试平台
`timescale 1ns/1ps
module tb_ccl;
    reg clk, rst_n;
    reg [7:0] i_bin, i_enh;
    reg bin_valid, enh_valid;
    wire o_valid;
    wire [7:0] o_data;
    reg o_ready;

    reg [7:0] bin_mem [0:4095];
    reg [7:0] enh_mem [0:4095];

    candidate_extract uut (
        .clk(clk), .rst_n(rst_n),
        .i_bin(i_bin), .i_bin_valid(bin_valid),
        .i_enh(i_enh), .i_enh_valid(enh_valid),
        .o_valid(o_valid), .o_data(o_data), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file, idle;

    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        $dumpfile("tb_ccl.vcd");
        $dumpvars(0, tb_ccl);
        if ($fopen("input_bin.hex","r") == 0) begin $display("ERROR: 缺 input_bin.hex，请先运行 pl/tools/gen_ccl_stimulus.py"); $finish; end
        if ($fopen("input_enh.hex","r") == 0) begin $display("ERROR: 缺 input_enh.hex，请先运行 pl/tools/gen_ccl_stimulus.py"); $finish; end
        $readmemh("input_bin.hex", bin_mem);
        $readmemh("input_enh.hex", enh_mem);

        rst_n = 0; bin_valid = 0; enh_valid = 0; o_ready = 1;
        repeat (2) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        for (idx = 0; idx < 4096; idx = idx + 1) begin
            i_bin = bin_mem[idx]; bin_valid = 1'b1;
            @(posedge clk);
        end
        bin_valid = 1'b0;
        for (idx = 0; idx < 4096; idx = idx + 1) begin
            i_enh = enh_mem[idx]; enh_valid = 1'b1;
            @(posedge clk);
        end
        enh_valid = 1'b0;

        out_idx = 0; idle = 0;
        out_file = $fopen("output_ccl.hex", "w");
        while (out_idx < 36) begin
            @(posedge clk);
            if (o_valid) begin
                $fwrite(out_file, "%02X\n", o_data);
                out_idx = out_idx + 1;
                idle = 0;
            end else begin
                idle = idle + 1;
                if (idle > 500000) begin $display("WATCHDOG out_idx=%0d", out_idx); $finish; end
            end
        end
        $fclose(out_file);
        $display("CCL 收集到 %0d 个输出", out_idx);
        #50 $finish;
    end
endmodule
