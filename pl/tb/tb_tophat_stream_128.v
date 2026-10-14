// tb_tophat_stream_128.v —— 流式 Top-Hat 128x72 验证
`timescale 1ns/1ps
module tb_tophat_stream_128;
    reg clk, rst_n;
    reg [7:0] i_data;
    reg i_valid;
    wire [7:0] o_data;
    wire o_valid;
    reg o_ready;
    reg [7:0] in_mem [0:9215];

    tophat_5x5_stream #(.W(128), .H(72)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid),
        .o_data(o_data), .o_valid(o_valid), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file, idle;
    initial clk = 0; always #5 clk = ~clk;
    initial begin
        $readmemh("input_integration.hex", in_mem);
        rst_n = 0; i_valid = 0; o_ready = 1;
        repeat (2) @(posedge clk); rst_n = 1; @(posedge clk);
        idx = 0; out_idx = 0; idle = 0;
        out_file = $fopen("output_tophat_128.hex", "w");
        while (out_idx < 9216) begin
            @(posedge clk);
            if (idx < 9216) begin i_data = in_mem[idx]; i_valid = 1'b1; idx = idx + 1; end
            else i_valid = 1'b0;
            if (o_valid) begin $fwrite(out_file, "%02X\n", o_data); out_idx = out_idx + 1; idle = 0; end
            else begin idle = idle + 1; if (idle > 500000) begin $display("WATCHDOG %0d", out_idx); $finish; end end
        end
        $fclose(out_file);
        $display("tophat 128x72 收集 %0d", out_idx);
        #50 $finish;
    end
endmodule
