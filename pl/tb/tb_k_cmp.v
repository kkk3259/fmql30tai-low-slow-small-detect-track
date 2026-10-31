// K / FLOOR 敏感度对比：喂一整帧 640x360 灰度，收集候选表字节
// 用法： iverilog -g2005 -o k.vvp -s tb_k_cmp tb_k_cmp.v rtl\*.v
//        vvp k.vvp +FRAME=frame.hex +OUT=k1.txt
//   参数 K/FLOOR 用 -P 覆盖：iverilog ... -Ptb_k_cmp.K=0 -Ptb_k_cmp.FLOOR=2
`timescale 1ns/1ps
module tb_k_cmp;
    parameter W = 640;
    parameter H = 360;
    parameter SE = 5;
    parameter MODE = 0;
    parameter DENOISE = 1;
    parameter K = 1;
    parameter FLOOR = 3;
    parameter MAX_CAND = 16;

    localparam NPIX = W * H;
    localparam PADN = 4 * W + 256;      // 帧尾补喂，冲干净流水线

    reg clk = 0, rst_n = 0;
    always #10 clk = ~clk;              // 50 MHz

    reg [7:0] mem [0:NPIX-1];
    reg [7:0] din = 0;
    reg vin = 0;
    wire irdy, vout;
    wire [7:0] dout;
    reg ordy;
    initial ordy = 1'b1;

    ip2_top_stream #(.W(W), .H(H), .SE(SE), .MODE(MODE), .DENOISE(DENOISE),
                     .K(K), .FLOOR(FLOOR), .MAX_CAND(MAX_CAND)) dut (
        .clk(clk), .rst_n(rst_n),
        .i_data(din), .i_valid(vin), .i_ready(irdy),
        .o_data(dout), .o_valid(vout), .o_ready(ordy),
        .dbg_state(), .dbg_px(), .dbg_th_valid(), .dbg_cf_valid(),
        .dbg_cf_ready(), .dbg_ch_ready(), .dbg_ccl_vcnt());

    // 收集输出字节
    integer fo, nbyte = 0;
    reg [7:0] b0 = 8'hff;
    reg [8*256-1:0] fname;
    always @(posedge clk) begin
        if (vout && ordy) begin
            if (nbyte == 0) b0 <= dout;
            if (nbyte < 4096) $fwrite(fo, "%02x\n", dout);
            nbyte <= nbyte + 1;
        end
    end

    integer i, fi;
    reg [8*256-1:0] fframe;
    initial begin
        if (!$value$plusargs("FRAME=%s", fframe)) fframe = "frame.hex";
        if (!$value$plusargs("OUT=%s",   fname))  fname  = "cand.txt";
        fi = $fopen(fframe, "r");
        if (fi == 0) begin $display("OPEN_FAIL %0s", fframe); $finish; end
        for (i = 0; i < NPIX; i = i + 1) begin
            if ($fscanf(fi, "%h\n", mem[i]) != 1) begin
                $display("FRAME_TOO_SHORT at %0d", i); $finish;
            end
        end
        $fclose(fi);
        fo = $fopen(fname, "w");
        $display("FRAME_OK %0d px  K=%0d FLOOR=%0d SE=%0d MODE=%0d", NPIX, K, FLOOR, SE, MODE);

        rst_n = 0;
        repeat (32) @(posedge clk);
        rst_n = 1;

        // 喂整帧
        for (i = 0; i < NPIX; i = i + 1) begin
            din = mem[i]; vin = 1;
            @(posedge clk);
            while (!irdy) begin vin = 0; @(posedge clk); vin = 1; end
        end
        // 补喂
        vin = 1; din = 8'd0;
        for (i = 0; i < PADN; i = i + 1) begin
            @(posedge clk);
            while (!irdy) begin vin = 0; @(posedge clk); vin = 1; end
        end
        vin = 0;
        repeat (20000) @(posedge clk);

        $display("DONE bytes=%0d  n_cand=%0d", nbyte, b0);
        
        $fclose(fo);
        $finish;
    end
endmodule
