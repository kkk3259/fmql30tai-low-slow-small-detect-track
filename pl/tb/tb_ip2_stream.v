// tb_ip2_stream.v —— IP2 流式全链测试（128x72）
// 顶层现在有 i_ready（CFAR 需要为内部 PAD 列反压上游），激励必须按握手推进。
`timescale 1ns/1ps
module tb_ip2_stream;
    localparam NPIX = 9216;   // 128*72
    localparam PADN = 4*128 + 256;   // 帧尾补喂拍数

    reg clk, rst_n;
    reg [7:0] i_data;
    reg i_valid;
    wire i_ready;
    wire [7:0] o_data;
    wire o_valid;
    reg o_ready;

    reg [7:0] in_mem [0:NPIX-1];

    ip2_top_stream #(.W(128), .H(72)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid), .i_ready(i_ready),
        .o_data(o_data), .o_valid(o_valid), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file, idle;

    initial clk = 0;
    always #5 clk = ~clk;

    // 激励：按 i_ready 握手喂 128x72 像素
    initial begin
        $readmemh("input_integration.hex", in_mem);
        rst_n = 0; i_valid = 0; i_data = 0; o_ready = 1;
        repeat (3) @(posedge clk);
        #1 rst_n = 1;
        repeat (2) @(posedge clk);

        idx = 0;
        i_data = in_mem[0];
        i_valid = 1'b1;
        // 帧尾必须继续喂 PADN 个 0，否则流水线尾部的候选会被冻结成常数
        while (idx < NPIX + PADN) begin
            @(negedge clk);
            if (i_ready) begin
                idx = idx + 1;
                i_data = (idx < NPIX) ? in_mem[idx] : 8'd0;
            end
        end
        @(negedge clk);
        i_valid = 1'b0;
    end

    // 收集：36 字节候选（边喂边收）
    initial begin
        wait (rst_n === 1'b1);
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
                if (idle > 5000000) begin
                    $display("WATCHDOG out_idx=%0d", out_idx);
                    $fclose(out_file);
                    $finish;
                end
            end
        end
        $fclose(out_file);
        $display("IP2 流式全链收集到 %0d 个输出", out_idx);
        #50 $finish;
    end
endmodule
