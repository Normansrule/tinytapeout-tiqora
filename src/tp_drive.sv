// tp_drive: a strong driver for a net whose loads sit far apart.
//
// On the Tiny Tapeout build (TP_SKY130_DRIVE defined in src/config.json) each bit
// is a sky130_fd_sc_hd__buf_4. It can drive about 170 fF and keep its output edge
// under the 0.75 ns limit at the slow corner (ss, 100 C, 1.60 V), where a 1x
// flip-flop manages about 50 fF (sky130_fd_sc_hd liberty, ss_100C_1v60).
// Everywhere else (RTL simulation, formal, FPGA) it is a plain wire.
//
// Why by hand: OpenROAD sizes drivers from its global-route wire estimate, which
// on this tile was about half the extracted load, so a handful of register
// outputs reached 0.80-0.95 ns after routing (GitHub run 43929775392).
module tp_drive #(
    parameter int W = 1
) (
    input  wire logic [W-1:0] a,
    output wire logic [W-1:0] x
);
`ifdef TP_SKY130_DRIVE
    for (genvar i = 0; i < W; i++) begin : g_buf
        sky130_fd_sc_hd__buf_4 u_buf (.A(a[i]), .X(x[i]));
    end
`else
    assign x = a;
`endif
endmodule : tp_drive
