// rec_basys3.sv — a recorder that sits beside tb_basys3 and writes down what
// the simulated board shows, for the "Basys 3, simulated" animation
// (docs/tools/fpga_media.py). It changes nothing in the design or the bench:
// compile it as a second top module (-s tb_basys3 -s rec_basys3) and pass
// +REC=<file>; without +REC it does nothing.
//
// One line per change, in clk50 cycles since the recording started:
//   <cycle> rst <0|1>        the chip's reset (dut.rst_n)
//   <cycle> led <bin16>      the 16 LEDs, LD15 first (binary, so one undriven LED stays one x)
//   <cycle> in  <hex8>       ui_in, shown on the right two 7-segment digits
//   <cycle> out <hex8>       uo_out, shown on the left two digits
//   <cycle> btn <hex1>       {btnU, btnR, btnL, btnC}
//   <cycle> tx  <hex8>       a byte the board sent to the PC (RsTx)
//   <cycle> rx  <hex8>       a byte the PC sent to the board (RsRx)
// +RECDIV=<n> is the UART's clocks per bit (default 8, the bench's PROG_DIV).
// Shared unchanged by tiqora-skywater130 and tinytapeout-tiqora.
`timescale 1ns/1ps
module rec_basys3;
    integer fd = 0, cyc = 0, div = 8;
    string path;
    reg [15:0] led_q = 16'hxxxx; reg [7:0] in_q = 8'hxx, out_q = 8'hxx; reg [3:0] btn_q = 4'hx; reg rst_q = 1'bx;
    initial if ($value$plusargs("REC=%s", path)) begin
        if (!$value$plusargs("RECDIV=%d", div)) div = 8;
        fd = $fopen(path, "w");
        $fwrite(fd, "# rec_basys3: clk50 cycles, UART %0d clocks per bit\n", div);
    end
    wire [3:0] btn = {tb_basys3.btnU, tb_basys3.btnR, tb_basys3.btnL, tb_basys3.btnC};
    always @(posedge tb_basys3.dut.clk50) if (fd) begin
        cyc = cyc + 1;
        if (tb_basys3.dut.rst_n !== rst_q) begin rst_q = tb_basys3.dut.rst_n; $fwrite(fd, "%0d rst %b\n", cyc, rst_q); end
        if (tb_basys3.led !== led_q) begin led_q = tb_basys3.led; $fwrite(fd, "%0d led %b\n", cyc, led_q); end
        if (tb_basys3.dut.ui_in !== in_q) begin in_q = tb_basys3.dut.ui_in; $fwrite(fd, "%0d in %h\n", cyc, in_q); end
        if (tb_basys3.dut.uo_out !== out_q) begin out_q = tb_basys3.dut.uo_out; $fwrite(fd, "%0d out %h\n", cyc, out_q); end
        if (btn !== btn_q) begin btn_q = btn; $fwrite(fd, "%0d btn %h\n", cyc, btn_q); end
    end
    // both serial directions, decoded the way the bench's terminal does: wait half a bit, sample 8
    task automatic uart(input bit from_board);
        integer i, at; reg [7:0] b;
        @(posedge tb_basys3.dut.clk50);
        if (fd && tb_basys3.dut.rst_n === 1'b1 && (from_board ? tb_basys3.RsTx : tb_basys3.RsRx) === 1'b0) begin
            at = cyc;
            repeat (div / 2) @(posedge tb_basys3.dut.clk50);
            for (i = 0; i < 8; i = i + 1) begin repeat (div) @(posedge tb_basys3.dut.clk50); b[i] = from_board ? tb_basys3.RsTx : tb_basys3.RsRx; end
            repeat (div) @(posedge tb_basys3.dut.clk50);
            $fwrite(fd, "%0d %s %h\n", at, from_board ? "tx" : "rx", b);
        end
    endtask
    always uart(1'b1);
    always uart(1'b0);
endmodule
