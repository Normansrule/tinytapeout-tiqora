// basys3_top.sv — Tiqora-Serial on a Digilent Basys 3 (Artix-7 XC7A35T).
// The same RTL as the 1x2 Tiny Tapeout tile, unchanged; the board is its
// demo board, and the board's own USB serial port is its host link.
//   clock      100 MHz divided to 50 MHz -> 115,200 baud (clk / 434)
//   reset      btnC
//   ui_in      sw0..2 CAP0..2, RsRx (UART RX), btnL/sw4 CAP3, btnR/sw5 CAP4,
//              btnU/sw6 CAP5, sw7 CAP6
//   uio_in[0]  btnD / sw8 CAP7
//   uo_out     LEDs 0..7; uo_out[4] (TX) is also RsTx
//   uio_out    LEDs 9..15 (ACT and the live event-queue bits)
`default_nettype none
module basys3_top (
    input  wire logic        clk,
    input  wire logic        btnC, btnL, btnR, btnU, btnD,
    input  wire logic [15:0] sw,
    output logic      [15:0] led,
    output logic      [6:0]  seg,
    output logic             dp,
    output logic      [3:0]  an,
    input  wire logic        RsRx,
    output logic             RsTx
);
    logic clk_div = 1'b0, clk50;
    always_ff @(posedge clk) clk_div <= ~clk_div;
`ifdef SYNTHESIS
    BUFG u_bufg (.I(clk_div), .O(clk50));
`else
    assign clk50 = clk_div;
`endif
    logic [3:0] btn_sync = 4'hF;
    logic [7:0] por = 8'd0;
    always_ff @(posedge clk50) begin
        btn_sync <= {btn_sync[2:0], btnC};
        if (por != 8'hFF) por <= por + 8'd1;
    end
    wire rst_n = (por == 8'hFF) && !btn_sync[3];

    logic [7:0] ui_in, uo_out, uio_in, uio_out, uio_oe;
    assign ui_in  = {sw[7], sw[6] | btnU, sw[5] | btnR, sw[4] | btnL, RsRx, sw[2:0]};
    assign uio_in = {7'b0, sw[8] | btnD};
    tt_um_normansrule_tiqora_serial u_chip (
        .ui_in(ui_in), .uo_out(uo_out), .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
        .ena(1'b1), .clk(clk50), .rst_n(rst_n));

    assign RsTx = uo_out[4];
    assign led  = {uio_out[7:1], rst_n, uo_out};

    logic [16:0] scan = 17'd0;
    always_ff @(posedge clk50) scan <= scan + 17'd1;
    wire  [1:0] digit = scan[16:15];
    logic [3:0] hex;
    always_comb begin
        unique case (digit)
            2'd0: hex = ui_in[3:0];
            2'd1: hex = ui_in[7:4];
            2'd2: hex = uo_out[3:0];
            default: hex = uo_out[7:4];
        endcase
        an = ~(4'b0001 << digit);
        unique case (hex)
            4'h0: seg = 7'b1000000; 4'h1: seg = 7'b1111001; 4'h2: seg = 7'b0100100; 4'h3: seg = 7'b0110000;
            4'h4: seg = 7'b0011001; 4'h5: seg = 7'b0010010; 4'h6: seg = 7'b0000010; 4'h7: seg = 7'b1111000;
            4'h8: seg = 7'b0000000; 4'h9: seg = 7'b0010000; 4'hA: seg = 7'b0001000; 4'hB: seg = 7'b0000011;
            4'hC: seg = 7'b1000110; 4'hD: seg = 7'b0100001; 4'hE: seg = 7'b0000110; default: seg = 7'b0001110;
        endcase
    end
    assign dp = ~(digit == 2'd2);
endmodule
