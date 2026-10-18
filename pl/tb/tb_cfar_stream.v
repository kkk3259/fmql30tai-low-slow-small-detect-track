// tb_cfar_stream.v —— 流式 CFAR 测试（64x64）
// 单趟流水版 CFAR 在虚拟光栅的 PAD 列（每行末尾 HALF 个）会拉低 i_ready 暂停，
// 因此激励必须按 ready/valid 握手推进：valid 保持、仅在握手成功时换下一个像素。
// 输出收集放在独立块里（边喂边收），因为有效输出在喂数阶段就已经开始产生。
`timescale 1ns/1ps
module tb_cfar_stream;
    localparam NPIX = 4096;

    reg clk, rst_n;
    reg [7:0] i_data;
    reg i_valid;
    wire i_ready;
    wire [7:0] o_data;
    wire [7:0] o_enh;
    wire o_valid;
    reg o_ready;

    reg [7:0] in_mem [0:NPIX-1];

    cfar_threshold_stream #(.W(64), .H(64)) uut (
        .clk(clk), .rst_n(rst_n),
        .i_data(i_data), .i_valid(i_valid), .i_ready(i_ready),
        .o_data(o_data), .o_enh(o_enh), .o_valid(o_valid), .o_ready(o_ready)
    );

    integer idx, out_idx, out_file, idle, fin;
    reg consumed;          // 上一拍是否完成一次有效握手

    // 握手取样：写入独立触发器，避免与激励块竞争
    always @(posedge clk) begin
        if (!rst_n) consumed <= 1'b0;
        else        consumed <= i_valid & i_ready;
    end

    initial clk = 0;
    always #5 clk = ~clk;

    // ---- 激励：复位后按握手喂像素 ----
    initial begin
        if ($fopen("input_cfar.hex","r") == 0) begin
            $display("ERROR: 缺 input_cfar.hex，请先运行 pl/tools/gen_cfar_stimulus.py");
            $finish;
        end
        $readmemh("input_cfar.hex", in_mem);

        rst_n = 0; i_valid = 0; o_ready = 0;
        repeat (2) @(posedge clk);
        #1 rst_n = 1;
        repeat (2) @(posedge clk);

        idx = 0;
        i_data  = in_mem[0];
        i_valid = 1'b1;
        while (idx < NPIX) begin
            @(negedge clk);            // negedge 更新，数据在 posedge 稳定
            if (consumed) begin
                idx = idx + 1;
                if (idx < NPIX) i_data = in_mem[idx];
            end
        end
        @(negedge clk);
        i_valid = 1'b0;
    end

    // ---- 收集：只收有效输出，顺序写文件 ----
    initial begin
        out_idx = 0; idle = 0; fin = 0;
        out_file = $fopen("output_cfar_stream.hex", "w");
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
                if (idle > 1000000) begin
                    $display("WATCHDOG out_idx=%0d", out_idx);
                    fin = 1;
                end
            end
        end
        $fclose(out_file);
        $display("流式 CFAR 收集到 %0d 个输出像素", out_idx);
        #50 $finish;
    end
endmodule
