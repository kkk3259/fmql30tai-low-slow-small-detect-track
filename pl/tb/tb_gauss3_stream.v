// tb_gauss3_stream.v —— 流式高斯测试平台（边喂入边收集）
`timescale 1ns/1ps
module tb_gauss3_stream;
    reg clk, rst_n;
    reg [7:0] s_data;
    reg s_valid, s_last;
    wire s_ready;
    wire [7:0] m_data;
    wire m_valid, m_last;
    reg m_ready;

    reg [7:0] in_mem [0:255];

    gauss3_stream #(.W(16), .H(16)) uut (
        .clk(clk), .rst_n(rst_n),
        .s_axis_tdata(s_data), .s_axis_tvalid(s_valid), .s_axis_tready(s_ready), .s_axis_tlast(s_last),
        .m_axis_tdata(m_data), .m_axis_tvalid(m_valid), .m_axis_tready(m_ready), .m_axis_tlast(m_last)
    );

    integer idx, out_idx, out_file, idle;

    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        $dumpfile("tb_gauss3_stream.vcd");
        $dumpvars(0, tb_gauss3_stream);
        $readmemh("input_gauss.hex", in_mem);

        rst_n = 0; s_valid = 0; s_last = 0; m_ready = 1;
        repeat (2) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        out_idx = 0; idle = 0;
        out_file = $fopen("output_gauss.hex", "w");
        // 边喂入边收集（流水线输出有延迟）
        for (idx = 0; idx < 256; idx = idx + 1) begin
            s_data = in_mem[idx];
            s_valid = 1'b1;
            s_last = (idx == 255);
            @(posedge clk);
            if (m_valid) begin
                $fwrite(out_file, "%02X\n", m_data);
                out_idx = out_idx + 1;
            end
        end
        s_valid = 1'b0; s_last = 1'b0;
        // 排空剩余输出
        while (out_idx < 256) begin
            @(posedge clk);
            if (m_valid) begin
                $fwrite(out_file, "%02X\n", m_data);
                out_idx = out_idx + 1;
                idle = 0;
            end else begin
                idle = idle + 1;
                if (idle > 10000) begin
                    $display("WATCHDOG out_idx=%0d", out_idx);
                    $finish;
                end
            end
        end
        $fclose(out_file);
        $display("流式高斯收集到 %0d 个像素", out_idx);
        #50 $finish;
    end
endmodule
