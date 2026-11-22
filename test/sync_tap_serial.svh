    // The timing unit inside this chip, recorded for sync_model.py
    // (+SYNCTAP=<file>; see sync_tap.sv and `make syncdiff`).
    sync_tap #(.NCH(8), .NCMP(3), .DEPTH(2), .PTRW(1), .FRACW(24), .FILTW(0), .PWW(16)) u_tap (
        .clk(clk), .rst(dut.u_sync.rst), .cap(dut.u_sync.cap_pin),
        .t_valid(dut.u_sync.t_valid), .t_op(dut.u_sync.t_op), .t_sub(dut.u_sync.t_sub),
        .t_rs1(dut.u_sync.t_rs1), .t_rs2(dut.u_sync.t_rs2),
        .reg_req(dut.u_sync.reg_req), .reg_addr(dut.u_sync.reg_addr),
        .reg_we(dut.u_sync.reg_we), .reg_wdata(dut.u_sync.reg_wdata),
        .trig(dut.u_sync.trig_pin), .evt_pending(dut.u_sync.evt_pending), .ovf(dut.u_sync.ovf_pin),
        .t_rdata(dut.u_sync.t_rdata), .t_now(dut.u_sync.t_now), .reg_rdata(dut.u_sync.reg_rdata),
        .status(dut.u_sync.status_out), .head(dut.u_sync.head_out)
    );
