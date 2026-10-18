// tb_tophat_stream.v —— 流式 5x5 Top-Hat 测试（32x32）
// 激励按 i_ready 握手（negedge 更新数据，避免与 DUT 的 posedge 采样竞争），
// 帧尾补喂 PADN 个 0，收集放在独立的 initial 块里边喂边收。
`timescale 1ns/1ps
module tb_tophat_stream;
    localparam NPIX = 1024;          // 32*32
    localparam PADN = 4*32 + 256;    // 帧尾补喂拍数

    reg clk, rst_n;
    reg [7:0] i_data;
    reg i_valid;
    wire i_ready;
    wire [7:0] o_data;
    wire o_valid;
    reg o_ready;

    reg [7:0] in_mem [0:NPIX-1];   // 32*32

    tophat_5x5_stream #(.W(32), .H(32)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid), .i_ready(i_ready),
        .o_data(o_data), .o_valid(o_valid), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file, idle;

    initial clk = 0;
    always #5 clk = ~clk;

    // 激励：按握手喂 NPIX 个像素 + PADN 个尾部填充
    initial begin
        if ($fopen("input_gray.hex","r") == 0) begin
            $display("ERROR: 缺 input_gray.hex，请先运行 pl/tools/gen_ip2_stimulus.py");
            $finish;
        end
        $readmemh("input_gray.hex", in_mem);

        rst_n = 0; i_valid = 0; i_data = 0; o_ready = 1;
        repeat (3) @(posedge clk);
        #1 rst_n = 1;
        repeat (2) @(posedge clk);

        idx = 0;
        i_data = in_mem[0];
        i_valid = 1'b1;
        @(negedge clk);
        while (idx < NPIX + PADN) begin
            if (i_ready) begin
                idx = idx + 1;
                i_data = (idx < NPIX) ? in_mem[idx] : 8'd0;
            end
            @(negedge clk);
        end
        i_valid = 1'b0;
    end

    // 收集：边喂边收
    initial begin
        wait (rst_n === 1'b1);
        out_idx = 0; idle = 0;
        out_file = $fopen("output_tophat_stream.hex", "w");
        while (out_idx < NPIX) begin
            @(posedge clk);
            if (o_valid) begin
                $fwrite(out_file, "%02X\n", o_data);
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
