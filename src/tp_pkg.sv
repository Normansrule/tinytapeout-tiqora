// tp_pkg.sv — shared types and ISA constants for the Tiqora core.
// One package, imported everywhere. ISA constants live here only.
`default_nettype none

package tp_pkg;

    // Tiqora-Serial has no core, so it uses none of the RV32I and Xpulse
    // constants below; they stay so this package matches the full chip's.
    // The waiver covers this package only: an unused parameter anywhere
    // else still fails `make lint` and the Tiny Tapeout linter.
    /* verilator lint_off UNUSEDPARAM */

    // ---------------------------------------------------------------
    // RV32I base opcodes (inst[6:0])
    // ---------------------------------------------------------------
    localparam logic [6:0] OPC_LUI     = 7'b0110111;
    localparam logic [6:0] OPC_AUIPC   = 7'b0010111;
    localparam logic [6:0] OPC_JAL     = 7'b1101111;
    localparam logic [6:0] OPC_JALR    = 7'b1100111;
    localparam logic [6:0] OPC_BRANCH  = 7'b1100011;
    localparam logic [6:0] OPC_LOAD    = 7'b0000011;
    localparam logic [6:0] OPC_STORE   = 7'b0100011;
    localparam logic [6:0] OPC_OPIMM   = 7'b0010011;
    localparam logic [6:0] OPC_OP      = 7'b0110011;
    localparam logic [6:0] OPC_FENCE   = 7'b0001111;
    localparam logic [6:0] OPC_SYSTEM  = 7'b1110011;
    // Xpulse time extension lives in the RISC-V custom-0 encoding space.
    localparam logic [6:0] OPC_CUSTOM0 = 7'b0001011;

    // ---------------------------------------------------------------
    // Xpulse funct3 map (opcode = OPC_CUSTOM0)
    // ---------------------------------------------------------------
    localparam logic [2:0] TF3_TIME  = 3'b000;  // TIME   rd
    localparam logic [2:0] TF3_POP   = 3'b001;  // TPOP   rd
    localparam logic [2:0] TF3_STAT  = 3'b010;  // TSTAT  rd
    localparam logic [2:0] TF3_WAIT  = 3'b011;  // TWAIT  rs1
    localparam logic [2:0] TF3_ARM   = 3'b100;  // TARM   rs1, rs2
    localparam logic [2:0] TF3_PULSE = 3'b101;  // TPULSE rs1
    localparam logic [2:0] TF3_MARK  = 3'b110;  // TMARK  rd, rs1
    localparam logic [2:0] TF3_CTL   = 3'b111;  // TADJ/TRATE/TCFG/TPW by funct7

    // Sub-ops carried in funct7 when funct3 == TF3_CTL
    localparam logic [6:0] TCTL_ADJ  = 7'd0;    // TADJ  rs1 — step the timebase
    localparam logic [6:0] TCTL_RATE = 7'd1;    // TRATE rs1 — fractional rate
    localparam logic [6:0] TCTL_CFG  = 7'd2;    // TCFG  rs1 — capture config
    localparam logic [6:0] TCTL_PW   = 7'd3;    // TPW   rs1 — trigger pulse width

    // ---------------------------------------------------------------
    // Datapath control encodings
    //
    // These are localparams on plain vectors rather than SystemVerilog
    // enums and structs, and that is a synthesis requirement, not a style
    // choice. Yosys's native Verilog frontend — which is what the
    // Tiny Tapeout hardening flow runs — accepts packages and file-scope
    // `import`, but it does NOT accept a typedef'd enum or packed struct
    // used as a port or as a variable declaration. A design written that
    // way needs the yosys-slang plugin to synthesize at all. Depending on
    // a plugin being present in somebody else's continuous integration is
    // not a risk worth taking for a tapeout, so the types are spelled out.
    // ---------------------------------------------------------------

    // ALU operation, ALU_W bits. Shifts are NOT here: they live in
    // tp_shifter so the ALU critical path is one 33-bit adder.
    localparam logic [3:0] ALU_ADD    = 4'd0;
    localparam logic [3:0] ALU_SUB    = 4'd1;
    localparam logic [3:0] ALU_AND    = 4'd2;
    localparam logic [3:0] ALU_OR     = 4'd3;
    localparam logic [3:0] ALU_XOR    = 4'd4;
    localparam logic [3:0] ALU_SLT    = 4'd5;
    localparam logic [3:0] ALU_SLTU   = 4'd6;
    localparam logic [3:0] ALU_COPY_B = 4'd7;   // LUI
    localparam logic [3:0] ALU_COPY_A = 4'd8;   // pass-through for time ops

    // Shift operation
    localparam logic [1:0] SH_NONE = 2'd0;
    localparam logic [1:0] SH_SLL  = 2'd1;
    localparam logic [1:0] SH_SRL  = 2'd2;
    localparam logic [1:0] SH_SRA  = 2'd3;

    // Immediate format select
    localparam logic [2:0] IMM_I    = 3'd0;
    localparam logic [2:0] IMM_S    = 3'd1;
    localparam logic [2:0] IMM_B    = 3'd2;
    localparam logic [2:0] IMM_U    = 3'd3;
    localparam logic [2:0] IMM_J    = 3'd4;
    localparam logic [2:0] IMM_NONE = 3'd5;

    // Writeback source select
    localparam logic [2:0] WB_ALU   = 3'd0;
    localparam logic [2:0] WB_SHIFT = 3'd1;
    localparam logic [2:0] WB_MEM   = 3'd2;
    localparam logic [2:0] WB_PC4   = 3'd3;
    localparam logic [2:0] WB_TIME  = 3'd4;

    // ---------------------------------------------------------------
    // Control bundle.
    //
    // tp_decode packs these fields into one CTRL_W-bit vector and
    // tp_core unpacks them again. The two concatenations must list the
    // fields in the SAME order, which is the order below, most significant
    // first. That is one place to get wrong instead of nineteen, and the
    // test suite catches a mismatch immediately.
    //
    //   [36]     legal        [35]     rf_we        [34:32] wb_sel
    //   [31:28]  alu_op       [27:26]  shift_op     [25]    alu_a_pc
    //   [24]     alu_b_imm    [23:21]  imm_sel      [20]    is_branch
    //   [19]     is_jal       [18]     is_jalr      [17]    mem_read
    //   [16]     mem_write    [15:13]  funct3       [12]    is_time
    //   [11:9]   time_op      [8:2]    time_sub     [1]     is_fence
    //   [0]      is_system
    // ---------------------------------------------------------------
    localparam int CTRL_W = 37;

    // ---------------------------------------------------------------
    // Sync unit register offsets (word index within 0x2000_0000)
    // ---------------------------------------------------------------
    localparam logic [3:0] SR_TIME  = 4'h0;  // R   current timebase
    localparam logic [3:0] SR_EVENT = 4'h1;  // R   pop one event (destructive)
    localparam logic [3:0] SR_STAT  = 4'h2;  // R   status
    localparam logic [3:0] SR_CFG   = 4'h3;  // W   capture enable + edge select
    localparam logic [3:0] SR_CMP0  = 4'h4;  // W   compare 0 deadline
    localparam logic [3:0] SR_CMP1  = 4'h5;  // W   compare 1 deadline
    // offset 6 is deliberately unmapped: the third compare channel is
    // reachable through TARM only. Widening the memory-mapped decode was
    // not worth the gates.
    localparam logic [3:0] SR_PW    = 4'h7;  // W   trigger pulse width
    localparam logic [3:0] SR_ADJ   = 4'h8;  // W   step the timebase (signed)
    localparam logic [3:0] SR_RATE  = 4'h9;  // W   fractional rate increment
    localparam logic [3:0] SR_PULSE = 4'hA;  // W   fire triggers now

    // ---------------------------------------------------------------
    // Address map (decoded on addr[31:28] in tp_bus)
    // ---------------------------------------------------------------
    localparam logic [3:0] DEV_FLASH = 4'h0;  // 0x0xxx_xxxx external QSPI flash
    localparam logic [3:0] DEV_PSRAM = 4'h1;  // 0x1xxx_xxxx external QSPI PSRAM
    localparam logic [3:0] DEV_SYNC  = 4'h2;  // 0x2xxx_xxxx sync unit registers

    /* verilator lint_on UNUSEDPARAM */

endpackage : tp_pkg
