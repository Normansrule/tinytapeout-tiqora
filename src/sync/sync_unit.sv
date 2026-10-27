// sync_unit.sv — the synchronisation block: timebase, capture, queue,
// compare, and the two ways software reaches them.
//
// Two access paths on purpose, and the difference between them is the
// argument for the whole Xpulse extension:
//
//   Xpulse instruction : 0 extra clocks. TIME rd puts the live timebase in
//                         a register in the same clock the instruction
//                         retires.
//   memory-mapped load  : the same value at 0x2000_0000, but it is a load,
//                         so it goes out over the data bus and comes back.
//                         Useful for a host or a debugger, wasteful in a
//                         control loop.
//
// Event arbitration: if several channels edge on the same clock they all
// carry the SAME timestamp and they all have to be queued. The pending-mask
// drain below pushes one per clock until the backlog is empty, so no event
// is dropped just because two sensors fired together — which, on a robot,
// they constantly do.
`default_nettype none

module sync_unit
#(
    parameter int NCH   = 8,       // capture channels
    parameter int NCMP  = 2,       // compare/trigger channels
    parameter int DEPTH = 2,       // event queue depth
    parameter int PTRW  = 1,       // $clog2(DEPTH)
    parameter int FRACW = 24,      // rate accumulator width
    parameter int FILTW = 0,       // capture glitch filter length
    parameter int PWW   = 16       // trigger pulse-width counter bits
) (
    input  wire  logic            clk,
    input  wire  logic            rst,

    // pins
    input  wire  logic [NCH-1:0]  cap_pin,
    output logic [NCMP-1:0]       trig_pin,
    output logic                  evt_pending,   // queue not empty
    output logic                  ovf_pin,       // sticky overflow

    // Xpulse instruction port (from tp_core)
    input  wire  logic            t_valid,
    input  wire  logic [2:0]      t_op,
    input  wire  logic [6:0]      t_sub,
    input  wire  logic [31:0]     t_rs1,
    input  wire  logic [31:0]     t_rs2,
    output logic [31:0]           t_rdata,
    output logic [31:0]           t_now,

    // memory-mapped port (from tp_bus)
    input  wire  logic            reg_req,
    input  wire  logic [3:0]      reg_addr,
    input  wire  logic            reg_we,
    input  wire  logic [31:0]     reg_wdata,
    output logic [31:0]           reg_rdata,

    // The status word and the head of the event queue, as ports. A parent
    // that wants these on pins must take them from here: reaching into
    // this module with a hierarchical reference simulates in Icarus and
    // is rejected by Yosys, so it would fail at hardening.
    output logic [31:0]           status_out,
    output logic [31:0]           head_out
);

    // -----------------------------------------------------------------
    // Declarations (all up front: this module wires five blocks together)
    // -----------------------------------------------------------------
    logic            rate_we, adj_we, cfg_we;
    logic [31:0]     rate_in, adj_in, cfg_in;
    logic [31:0]     now;

    logic [NCH-1:0]  cfg_en, cfg_fall;
    logic            cfg_both;
    logic [NCH-1:0]  evt, evt_rise, cap_level;

    logic [NCH-1:0]  pend_mask, pend_rise, work_mask, work_rise, sel_mask;
    logic [26:0]     pend_ts, work_ts;
    logic [2:0]      sel_ch;
    logic            have_work, hw_taken, backlog_lost;

    logic            fifo_push, fifo_pop, fifo_empty, fifo_full, fifo_ovf;
    logic [31:0]     fifo_wdata, fifo_rdata;
    logic [PTRW:0]   fifo_count;
    logic            sw_push;
    logic [31:0]     sw_wdata;

    logic            arm_we, pulse_we, pw_we;
    logic [31:0]     arm_time, pw_in;
    logic [1:0]      arm_sel;
    logic [NCMP-1:0] pulse_mask, armed;

    logic [31:0]     status;
    logic            t_pop, t_arm, t_pulse, t_mark, t_ctl, mm_we, mm_re;

    integer k;

    // -----------------------------------------------------------------
    // Timebase
    // -----------------------------------------------------------------
    sync_timebase #(.FRACW(FRACW)) u_time (
        .clk    (clk),
        .rst    (rst),
        .rate_we(rate_we),
        .rate_in(rate_in),
        .adj_we (adj_we),
        .adj_in (adj_in),
        .now    (now)
    );

    assign t_now = now;

    // -----------------------------------------------------------------
    // Capture configuration and lanes
    // -----------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (rst) begin
            cfg_en   <= '0;
            cfg_fall <= '0;
            cfg_both <= 1'b0;
        end else if (cfg_we) begin
            cfg_en   <= cfg_in[NCH-1:0];
            cfg_fall <= cfg_in[8 +: NCH];
            cfg_both <= cfg_in[16];
        end
    end

    sync_capture #(.NCH(NCH), .FILTW(FILTW)) u_cap (
        .clk     (clk),
        .rst     (rst),
        .pin     (cap_pin),
        .en      (cfg_en),
        .fall    (cfg_fall),
        .both    (cfg_both),
        .evt     (evt),
        .evt_rise(evt_rise),
        .level   (cap_level)
    );

    // -----------------------------------------------------------------
    // Event arbitration: lowest channel first, backlog drained one per clock
    // -----------------------------------------------------------------
    always_comb begin
        if (|evt) begin
            work_mask = evt;
            work_rise = evt_rise;
            work_ts   = now[26:0];
        end else begin
            work_mask = pend_mask;
            work_rise = pend_rise;
            work_ts   = pend_ts;
        end
        have_work = |work_mask;

        // descending scan so the lowest set bit is the one that sticks
        sel_ch = 3'd0;
        for (k = NCH-1; k >= 0; k = k - 1)
            if (work_mask[k]) sel_ch = k[2:0];

        sel_mask = {{(NCH-1){1'b0}}, 1'b1} << sel_ch;
    end

    assign fifo_push  = have_work;
    assign fifo_wdata = {1'b0, sel_ch, work_rise[sel_ch], work_ts};

    // A TMARK in the same clock takes the queue slot; the pin event then
    // stays in the backlog and goes in a clock later with its own timestamp.
    assign hw_taken = have_work && !sw_push;

    // New edges replace the backlog. Whatever was still waiting in it is
    // lost, so it counts as an overflow rather than vanishing.
    assign backlog_lost = (|evt) && (|pend_mask);

    always_ff @(posedge clk) begin
        if (rst) begin
            pend_mask <= '0;
            pend_rise <= '0;
            pend_ts   <= '0;
        end else if (|evt) begin
            pend_mask <= hw_taken ? (evt & ~sel_mask) : evt;
            pend_rise <= evt_rise;
            pend_ts   <= now[26:0];
        end else if (hw_taken) begin
            pend_mask <= work_mask & ~sel_mask;
        end
    end

    sync_event_fifo #(.DEPTH(DEPTH), .PTRW(PTRW)) u_fifo (
        .clk     (clk),
        .rst     (rst),
        .push    (fifo_push || sw_push),
        .wdata   (sw_push ? sw_wdata : fifo_wdata),
        .pop     (fifo_pop),
        .lost    (backlog_lost),
        .rdata   (fifo_rdata),
        .empty   (fifo_empty),
        .full    (fifo_full),
        .count   (fifo_count),
        .overflow(fifo_ovf)
    );

    // -----------------------------------------------------------------
    // Compare / trigger
    // -----------------------------------------------------------------
    sync_compare #(.NCMP(NCMP), .PWW(PWW)) u_cmp (
        .clk       (clk),
        .rst       (rst),
        .now       (now),
        .arm_we    (arm_we),
        .arm_time  (arm_time),
        .arm_sel   (arm_sel),
        .pulse_we  (pulse_we),
        .pulse_mask(pulse_mask),
        .pw_we     (pw_we),
        .pw_in     (pw_in),
        .trig      (trig_pin),
        .armed     (armed)
    );

    // -----------------------------------------------------------------
    // Status word
    // -----------------------------------------------------------------
    always_comb begin
        status             = 32'd0;
        status[PTRW:0]     = fifo_count;
        status[4]          = fifo_empty;
        status[5]          = fifo_full;
        status[6]          = fifo_ovf;
        status[8 +: NCMP]  = armed;
        status[12 +: NCMP] = trig_pin;
        status[16 +: NCH]  = cap_level;
    end

    assign evt_pending = ~fifo_empty;
    assign status_out  = status;
    assign head_out    = fifo_rdata;
    assign ovf_pin     = fifo_ovf;

    // -----------------------------------------------------------------
    // Xpulse instruction decode. TMARK pushes a software event so a
    // software timestamp lands in the same ordered queue as the hardware
    // ones — that is how you correlate "when the code saw it" against
    // "when the pin moved".
    // -----------------------------------------------------------------
    assign t_pop   = t_valid && (t_op == tp_pkg::TF3_POP);
    assign t_arm   = t_valid && (t_op == tp_pkg::TF3_ARM);
    assign t_pulse = t_valid && (t_op == tp_pkg::TF3_PULSE);
    assign t_mark  = t_valid && (t_op == tp_pkg::TF3_MARK);
    assign t_ctl   = t_valid && (t_op == tp_pkg::TF3_CTL);

    assign sw_push  = t_mark;
    assign sw_wdata = {1'b1, t_rs1[2:0], 1'b1, now[26:0]};

    always_comb begin
        unique case (t_op)
            tp_pkg::TF3_TIME: t_rdata = now;
            tp_pkg::TF3_POP:  t_rdata = fifo_empty ? 32'd0 : fifo_rdata;
            tp_pkg::TF3_STAT: t_rdata = status;
            tp_pkg::TF3_MARK: t_rdata = now;
            default:  t_rdata = now;
        endcase
    end

    // -----------------------------------------------------------------
    // Memory-mapped register port (combinational read, single cycle)
    // -----------------------------------------------------------------
    assign mm_we = reg_req &&  reg_we;
    assign mm_re = reg_req && !reg_we;

    always_comb begin
        unique case (reg_addr)
            tp_pkg::SR_TIME:  reg_rdata = now;
            tp_pkg::SR_EVENT: reg_rdata = fifo_empty ? 32'd0 : fifo_rdata;
            tp_pkg::SR_STAT:  reg_rdata = status;
            default:  reg_rdata = 32'd0;
        endcase
    end

    // Both access paths drive the same strobes.
    always_comb begin
        fifo_pop   = t_pop   || (mm_re && (reg_addr == tp_pkg::SR_EVENT));
        arm_we     = t_arm   || (mm_we && ((reg_addr == tp_pkg::SR_CMP0) ||
                                           (reg_addr == tp_pkg::SR_CMP1)));
        arm_time   = t_arm   ? t_rs1 : reg_wdata;
        arm_sel    = t_arm   ? t_rs2[1:0]
                             : ((reg_addr == tp_pkg::SR_CMP1) ? 2'd1 : 2'd0);
        pulse_we   = t_pulse || (mm_we && (reg_addr == tp_pkg::SR_PULSE));
        pulse_mask = t_pulse ? t_rs1[NCMP-1:0] : reg_wdata[NCMP-1:0];
        pw_we      = (t_ctl && (t_sub == tp_pkg::TCTL_PW))   ||
                     (mm_we && (reg_addr == tp_pkg::SR_PW));
        pw_in      = t_ctl   ? t_rs1 : reg_wdata;
        cfg_we     = (t_ctl && (t_sub == tp_pkg::TCTL_CFG))  ||
                     (mm_we && (reg_addr == tp_pkg::SR_CFG));
        cfg_in     = t_ctl   ? t_rs1 : reg_wdata;
        adj_we     = (t_ctl && (t_sub == tp_pkg::TCTL_ADJ))  ||
                     (mm_we && (reg_addr == tp_pkg::SR_ADJ));
        adj_in     = t_ctl   ? t_rs1 : reg_wdata;
        rate_we    = (t_ctl && (t_sub == tp_pkg::TCTL_RATE)) ||
                     (mm_we && (reg_addr == tp_pkg::SR_RATE));
        rate_in    = t_ctl   ? t_rs1 : reg_wdata;
    end

    wire _unused = &{1'b0, fifo_full, t_rs2[31:2], cfg_in[31:17], 1'b0};

endmodule : sync_unit
