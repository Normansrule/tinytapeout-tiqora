// tp_sync_soc.sv — the 1x1 system: sync unit plus a serial host port.
//
// No core, no external memory, no QSPI. The timestamping and trigger
// hardware is identical to the full chip — same modules, same register
// map, same event format — and a host drives it over the serial port
// instead of a RISC-V core driving it over a bus.
//
// That is the whole point of the 1x1 build: every claim about timestamp
// resolution, capture latency and trigger jitter holds here too, because
// it is the same logic. What you give up is running a program on the
// chip; the policy loop runs on the host instead.
`default_nettype none

module tp_sync_soc #(
    parameter int NCH   = 8,
    parameter int NCMP  = 3,
    parameter int DEPTH = 2,
    parameter int PTRW  = 1,
    parameter int FRACW = 24,
    parameter int FILTW = 0,
    parameter int PWW   = 16,      // trigger pulse-width counter bits
    parameter int DIV   = 434,     // baud = clk_hz / DIV; 115200 at 50 MHz
    parameter int DIVW  = 9,
    parameter int TOW   = 20       // host frame timeout, 2^TOW clocks (21 ms at 50 MHz)
) (
    input  wire  logic            clk,
    input  wire  logic            rst,

    input  wire  logic [NCH-1:0]  cap_pin,
    output logic [NCMP-1:0]       trig_pin,
    output logic                  evt_pending,
    output logic                  evt_pulse,
    output logic                  ovf_pin,
    output logic                  heartbeat,

    // serial host port
    input  wire  logic            uart_rx,
    output logic                  uart_tx,
    output logic                  uart_active,

    // head-of-queue exposed for a logic analyser, free of charge
    output logic [2:0]            ev_chan,
    output logic                  ev_edge,
    output logic [PTRW:0]         ev_count
);

    logic        reg_req, reg_we;
    logic [3:0]  reg_addr;
    logic [31:0] reg_wdata, reg_rdata;
    logic [31:0] t_now, status, head;
    logic [31:0] t_rdata_unused;     // no core to read it

    tp_host_uart #(.DIV(DIV), .DIVW(DIVW), .TOW(TOW)) u_host (
        .clk      (clk),
        .rst      (rst),
        .rx_pin   (uart_rx),
        .tx_pin   (uart_tx),
        .reg_req  (reg_req),
        .reg_addr (reg_addr),
        .reg_we   (reg_we),
        .reg_wdata(reg_wdata),
        .reg_rdata(reg_rdata),
        .active   (uart_active)
    );

    sync_unit #(
        .NCH(NCH), .NCMP(NCMP), .DEPTH(DEPTH), .PTRW(PTRW),
        .FRACW(FRACW), .FILTW(FILTW), .PWW(PWW)
    ) u_sync (
        .clk        (clk),
        .rst        (rst),
        .cap_pin    (cap_pin),
        .trig_pin   (trig_pin),
        .evt_pending(evt_pending),
        .ovf_pin    (ovf_pin),
        // the Xpulse instruction port is unused without a core
        .t_valid    (1'b0),
        .t_op       (3'd0),
        .t_sub      (7'd0),
        .t_rs1      (32'd0),
        .t_rs2      (32'd0),
        .t_rdata    (t_rdata_unused),
        .t_now      (t_now),
        .reg_req    (reg_req),
        .reg_addr   (reg_addr),
        .reg_we     (reg_we),
        .reg_wdata  (reg_wdata),
        .reg_rdata  (reg_rdata),
        .status_out (status),
        .head_out   (head)
    );

    // one-clock pulse whenever the queue gains an entry: the cheapest
    // possible scope trigger for measuring pin-to-timestamp latency
    logic evt_pending_q;
    always_ff @(posedge clk) begin
        if (rst) evt_pending_q <= 1'b0;
        else     evt_pending_q <= evt_pending;
    end
    assign evt_pulse = evt_pending && !evt_pending_q;

    assign heartbeat = t_now[23];

    // Head-of-queue status on pins. These are already-computed signals,
    // so the pins cost wiring and nothing else, and they let a logic
    // analyser watch events without the host having to poll.
    assign ev_count = status[PTRW:0];
    assign ev_chan  = head[30:28];
    assign ev_edge  = head[27];

    wire _unused = &{1'b0, status[31:PTRW+1], head[31], head[26:0],
                     t_now[31:24], t_now[22:0], t_rdata_unused, 1'b0};

endmodule : tp_sync_soc
