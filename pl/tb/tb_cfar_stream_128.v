// tb_cfar_stream_128.v —— 流式 CFAR 128x72 验证（按 ready/valid 握手喂数）
`timescale 1ns/1ps
module tb_cfar_stream_128;
    localparam NPIX = 9216;

    reg clk, rst_n;
    reg [7:0] i_data;
    reg i_valid;
    wire i_ready;
    wire [7:0] o_data;
    wire [7:0] o_enh;
    wire o_valid;
    reg o_ready;
    reg [7:0] in_mem [0:NPIX-1];

    cfar_threshold_stream #(.W(128), .H(72)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid), .i_ready(i_ready),
        .o_data(o_data), .o_enh(o_enh), .o_valid(o_valid), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file, idle, fin;
    reg consumed;

    always @(posedge clk) begin
        if (!rst_n) consumed <= 1'b0;
        else        consumed <= i_valid & i_ready;
    end

    initial clk = 0; always #5 clk = ~clk;

    initial begin
        $readmemh("output_tophat_128.hex", in_mem);
        rst_n = 0; i_valid = 0; o_ready = 0;
        repeat (2) @(posedge clk);
        #1 rst_n = 1;
        repeat (2) @(posedge clk);

        idx = 0;
        i_data  = in_mem[0];
        i_valid = 1'b1;
        while (idx < NPIX) begin
            @(negedge clk);
            if (consumed) begin
                idx = idx + 1;
                if (idx < NPIX) i_data = in_mem[idx];
            end
        end
        @(negedge clk);
        i_valid = 1'b0;
    end

    initial begin
        out_idx = 0; idle = 0; fin = 0;
        out_file = $fopen("output_cfar_128_stream.hex", "w");
        @(posedge rst_n);
        repeat (2) @(posedge clk);
        o_ready = 1'b1;
        while (out_idx < NPIX && !fin) begin
            @(posedge clk);
            if (o_valid) begin
                $fwrite(out_file, "%02X\n", o_data);
                out_idx = out_idx + 1;
                idle = 0;
            end else begin
                idle = idle + 1;
                if (idle > 2000000) begin
                    $display("WATCHDOG %0d", out_idx);
                    fin = 1;
                end
            end
        end
        $fclose(out_file);
        $display("流式 CFAR 128x72 收集 %0d", out_idx);
        #50 $finish;
    end
endmodule
