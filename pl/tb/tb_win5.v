// tb_win5.v —— 单独测 win5 腐蚀（8x8，像素=行*8+列，便于手算验证）
`timescale 1ns/1ps
module tb_win5;
    reg clk, rst_n;
    reg [7:0] i_data;
    reg i_valid;
    wire i_ready;
    wire [7:0] o_data;
    wire o_valid;
    reg o_ready;

    reg [7:0] in_mem [0:63];

    win5 #(.W(8), .IS_MAX(0), .PAD(8'd255)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid), .i_ready(i_ready),
        .o_data(o_data), .o_valid(o_valid), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file, idle;
    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        if ($fopen("input_win5.hex","r") == 0) begin $display("ERROR: 缺 input_win5.hex"); $finish; end
        $readmemh("input_win5.hex", in_mem);
        rst_n = 0; i_valid = 0; o_ready = 1;
        repeat (2) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        out_idx = 0; idle = 0; idx = 0;
        out_file = $fopen("output_win5.hex", "w");
        while (out_idx < 64) begin
            @(posedge clk);
            if (idx < 64) begin i_data = in_mem[idx]; i_valid = 1'b1; idx = idx + 1; end
            else i_valid = 1'b0;
            if (o_valid) begin
                $fwrite(out_file, "%02X\n", o_data);
                if (out_idx < 8) $display("DBG #%0d o=%h", out_idx, o_data);
                out_idx = out_idx + 1; idle = 0;
            end else begin
                idle = idle + 1;
                if (idle > 100000) begin $display("WATCHDOG out_idx=%0d", out_idx); $finish; end
            end
        end
        $fclose(out_file);
        $display("win5 腐蚀收集到 %0d 像素", out_idx);
        #50 $finish;
    end
endmodule
