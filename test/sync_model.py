#!/usr/bin/env python3
"""sync_model.py — a reference model of the timing unit (src/sync/*.sv).

The model states the unit's behaviour in plain Python, one clock at a time
and with no nets or pipelines: a timebase that steps by 1 (0 or 2 when a
rate correction carries), two-flop pin synchronisers, one event per clock
into a FIFO in channel order, deadlines that fire on the exact tick, pulse
widths in clocks. It was written from the RTL's behaviour, so a mistake the
two share goes unseen; what it gives is a second, independent statement of
that behaviour that any change to the RTL has to agree with clock for clock.

    python3 sync_model.py sync_ref_trace.txt   # check one trace
    python3 sync_model.py --suite               # build and check 3 configurations

A trace from tb_sync_ref.sv holds the inputs and outputs of every clock; the
model replays the inputs and compares every output. It also checks one
promise across the run: a pin event is either queued or recorded by the
sticky overflow flag, never silently lost. Two cases broke it until
2026-10-26, both found by this model and both fixed in sync_unit.sv:

  * Edges on several channels in one clock are queued one per clock from a
    backlog, and a new edge before the backlog drains replaces it. The
    events still waiting are dropped; they now raise overflow.
  * When a TMARK and a pin event reach the queue in the same clock, the mark
    takes the slot. The pin event used to be dropped; it now stays in the
    backlog and is queued a clock later with its own timestamp.

This file is identical in Tiqora and Tiqora-Serial (docs/shared_timing.sha256).
"""
import sys

M32 = 0xFFFFFFFF

# Xpulse funct3 and TCTL sub-ops, memory-mapped register offsets (tp_pkg.sv)
TIME, POP, STAT, WAIT, ARM, PULSE, MARK, CTL = range(8)
ADJ, RATE, CFG, PW = range(4)
SR_TIME, SR_EVENT, SR_STAT, SR_CFG, SR_CMP0, SR_CMP1 = 0, 1, 2, 3, 4, 5
SR_PW, SR_ADJ, SR_RATE, SR_PULSE = 7, 8, 9, 0xA


class SyncModel:
    def __init__(self, nch, ncmp, depth, fracw, filtw, pww):
        self.nch, self.ncmp, self.depth = nch, ncmp, depth
        self.fracw, self.filtw, self.pww = fracw, filtw, pww
        self.chmask = (1 << nch) - 1
        self.mem = [None] * depth          # queue storage is not reset
        self.reset()

    def reset(self):
        self.now = 0
        self.frac = 0
        self.rate_mag = 0
        self.rate_neg = False
        self.sync0 = self.sync1 = 0
        self.shift = [0] * self.nch        # glitch filter history per channel
        self.stable = 0                    # filtered level (FILTW > 0)
        self.stable_q = 0
        self.en = self.fall = 0
        self.both = False
        self.pend_mask = self.pend_rise = self.pend_ts = 0
        self.cnt = self.rptr = self.wptr = 0
        self.ovf = False
        self.armed = [False] * self.ncmp
        self.deadline = [0] * self.ncmp
        self.pcnt = [0] * self.ncmp
        self.pw = 8

    # ---- what the unit shows during a clock (before the edge) ----
    def level(self):
        return self.sync1 if self.filtw == 0 else self.stable

    def events(self):
        lvl = self.level()
        rise = lvl & ~self.stable_q & self.chmask
        fall = ~lvl & self.stable_q & self.chmask
        if self.both:
            ev = rise | fall
        else:
            ev = (self.fall & fall) | (~self.fall & rise)
        return ev & self.en & self.chmask, rise

    def status(self):
        s = self.cnt
        s |= (self.cnt == 0) << 4
        s |= (self.cnt == self.depth) << 5
        s |= self.ovf << 6
        for i in range(self.ncmp):
            s |= self.armed[i] << (8 + i)
            s |= (self.pcnt[i] != 0) << (12 + i)
        s |= self.level() << 16
        return s

    def head(self):
        return self.mem[self.rptr]

    def outputs(self, i):
        trig = sum((self.pcnt[k] != 0) << k for k in range(self.ncmp))
        empty = self.cnt == 0
        pop_val = 0 if empty else self.head()
        t_rdata = {POP: pop_val, STAT: self.status()}.get(i["t_op"], self.now)
        reg_rdata = {SR_TIME: self.now, SR_EVENT: pop_val,
                     SR_STAT: self.status()}.get(i["reg_addr"], 0)
        return dict(trig=trig, evt_pending=int(not empty), ovf=int(self.ovf),
                    t_rdata=t_rdata, t_now=self.now, reg_rdata=reg_rdata,
                    status=self.status(), head=None if empty else self.head())

    # ---- the clock edge ----
    def step(self, i):
        """Advance one clock. Returns (pin events deferred by a TMARK, pin
        events dropped, pin events dropped with the overflow flag still
        clear afterwards)."""
        if i["rst"]:
            mem = self.mem
            self.reset()
            self.mem = mem
            return 0, 0, 0

        tv, op, sub = i["t_valid"], i["t_op"], i["t_sub"]
        rs1, rs2 = i["t_rs1"], i["t_rs2"]
        mw = i["reg_req"] and i["reg_we"]
        mr = i["reg_req"] and not i["reg_we"]
        a, wd = i["reg_addr"], i["reg_wdata"]
        ctl = tv and op == CTL

        # the instruction wins when both paths drive the same block
        pop = (tv and op == POP) or (mr and a == SR_EVENT)
        arm = (tv and op == ARM) or (mw and a in (SR_CMP0, SR_CMP1))
        arm_time = rs1 if tv and op == ARM else wd
        arm_sel = (rs2 & 3) if tv and op == ARM else (1 if a == SR_CMP1 else 0)
        pulse = (tv and op == PULSE) or (mw and a == SR_PULSE)
        pulse_mask = rs1 if tv and op == PULSE else wd
        val = rs1 if ctl else wd
        pw_we = (ctl and sub == PW) or (mw and a == SR_PW)
        cfg_we = (ctl and sub == CFG) or (mw and a == SR_CFG)
        adj_we = (ctl and sub == ADJ) or (mw and a == SR_ADJ)
        rate_we = (ctl and sub == RATE) or (mw and a == SR_RATE)
        mark = tv and op == MARK

        # events this clock, oldest backlog after the new edges
        ev, rise = self.events()
        ts = self.now & 0x7FFFFFF
        if ev:
            work, wrise, wts = ev, rise, ts
        else:
            work, wrise, wts = self.pend_mask, self.pend_rise, self.pend_ts
        hw_push = work != 0
        ch = (work & -work).bit_length() - 1 if work else 0
        hw_word = (ch << 28) | (((wrise >> ch) & 1) << 27) | wts

        # a software mark takes the queue slot; the pin event waits a clock
        hw_taken = hw_push and not mark
        done = (1 << ch) if hw_taken else 0
        # new edges replace the backlog rather than join it
        overwritten = bin(self.pend_mask).count("1") if ev else 0
        if ev:
            self.pend_mask, self.pend_rise, self.pend_ts = ev & ~done, rise, ts
        elif hw_taken:
            self.pend_mask = work & ~done

        # queue: one push per clock
        push = hw_push or mark
        word = ((1 << 31) | ((rs1 & 7) << 28) | (1 << 27) | ts) if mark else hw_word
        full = self.cnt == self.depth
        do_push = push and not full
        do_pop = pop and self.cnt != 0
        if do_push:
            self.mem[self.wptr] = word
            self.wptr = (self.wptr + 1) % self.depth
        if do_pop:
            self.rptr = (self.rptr + 1) % self.depth
        self.cnt += int(do_push) - int(do_pop)
        if (push and full) or overwritten:
            self.ovf = True
        dropped = overwritten + int(hw_taken and full)

        # deadlines and pulses
        for k in range(self.ncmp):
            reached = ((self.now + 1 - self.deadline[k]) & M32) < 0x80000000
            fire = (self.armed[k] and reached) or (pulse and (pulse_mask >> k) & 1)
            if arm and arm_sel == k:
                self.deadline[k], self.armed[k] = arm_time, True
            elif self.armed[k] and reached:
                self.armed[k] = False
            if fire:
                self.pcnt[k] = self.pw
            elif self.pcnt[k]:
                self.pcnt[k] -= 1
        if pw_we:
            self.pw = val & ((1 << self.pww) - 1)

        # capture configuration and pins
        if cfg_we:
            self.en = val & self.chmask
            self.fall = (val >> 8) & self.chmask
            self.both = bool((val >> 16) & 1)
        self.stable_q = self.level()
        if self.filtw:
            for c in range(self.nch):
                h = self.shift[c]
                full_ones = (1 << (self.filtw + 1)) - 1
                if h == full_ones:
                    self.stable |= 1 << c
                elif h == 0:
                    self.stable &= ~(1 << c)
                self.shift[c] = ((h << 1) | ((self.sync1 >> c) & 1)) & full_ones
        self.sync1 = self.sync0
        self.sync0 = i["cap"]

        # timebase: a rate correction adds or drops one tick on carry
        fsum = self.frac + self.rate_mag
        carry = fsum >> self.fracw
        step = (0 if carry else 1) if self.rate_neg else (2 if carry else 1)
        if rate_we:
            self.rate_mag = val & ((1 << self.fracw) - 1)
            self.rate_neg = bool(val >> 31)
            self.frac = 0
        else:
            self.frac = fsum & ((1 << self.fracw) - 1)
        self.now = (self.now + val + 1 if adj_we else self.now + step) & M32

        return int(hw_push and mark), dropped, dropped if not self.ovf else 0


def parse(line):
    ins, outs = line.split("|")
    f = ins.split()
    g = outs.split()
    i = dict(rst=int(f[0]), cap=int(f[1], 16), t_valid=int(f[2]), t_op=int(f[3]),
             t_sub=int(f[4]), t_rs1=int(f[5], 16), t_rs2=int(f[6], 16),
             reg_req=int(f[7]), reg_addr=int(f[8]), reg_we=int(f[9]),
             reg_wdata=int(f[10], 16))
    names = ["trig", "evt_pending", "ovf", "t_rdata", "t_now", "reg_rdata", "status", "head"]
    o = {}
    for n, v in zip(names, g):
        o[n] = None if "x" in v.lower() else int(v, 16 if n not in ("evt_pending", "ovf") else 10)
    return i, o


def run(path, show=5):
    lines = open(path).read().splitlines()
    hdr = dict(kv.split("=") for kv in lines[0][1:].split())
    m = SyncModel(int(hdr["NCH"]), int(hdr["NCMP"]), int(hdr["DEPTH"]),
                  int(hdr["FRACW"]), int(hdr["FILTW"]), int(hdr["PWW"]))
    bad, lost = 0, [0, 0, 0]
    for n, line in enumerate(lines[1:]):
        if "x" in line.split("|")[0].lower():
            # inputs are built from t_now, so unknown inputs mean time went X
            print(f"  clock {n}: the trace has unknown (x) inputs: the timebase went unknown")
            return hdr, n, bad + 1, lost
        i, o = parse(line)
        if i["rst"]:
            m.step(i)
            continue
        want = m.outputs(i)
        for k, v in o.items():
            if k == "head" and want["head"] is None:
                continue
            if v != want[k]:
                bad += 1
                if bad <= show:
                    print(f"  clock {n}: {k} is {v if v is None else hex(v)}, model says {hex(want[k]) if want[k] is not None else None}")
        lost = [a + b for a, b in zip(lost, m.step(i))]
    return hdr, len(lines) - 1, bad, lost


# Tiqora, Tiqora-Serial, and a set that exercises the corners the chips'
# parameters do not: 4 channels, 4 comparators, a 4-deep queue, the glitch
# filter, a narrow rate accumulator and pulse counter.
SUITE = [
    ("Tiqora", {}),
    ("Tiqora-Serial", {"NCMP": 3}),
    ("stress", {"NCH": 4, "NCMP": 4, "DEPTH": 4, "PTRW": 2, "FRACW": 8, "FILTW": 2, "PWW": 6}),
]


def suite(cycles=60000, seed=1):
    import glob, subprocess
    srcs = ["../src/tp_pkg.sv"] + sorted(glob.glob("../src/sync/*.sv")) + ["tb_sync_ref.sv"]
    fails, lost_all = 0, [0, 0, 0]
    for name, params in SUITE:
        ps = [f"-Ptb_sync_ref.{k}={v}" for k, v in params.items()]
        b = subprocess.run(["iverilog", "-g2012", "-o", "tb_sync_ref.vvp", "-s", "tb_sync_ref"] + ps + srcs,
                           capture_output=True, text=True)
        if b.returncode:
            print(b.stdout + b.stderr)
            fails += 1
            continue
        subprocess.run(["vvp", "-n", "tb_sync_ref.vvp", f"+SEED={seed}", f"+CYCLES={cycles}"],
                       check=True, capture_output=True)
        hdr, n, bad, lost = run("sync_ref_trace.txt")
        lost_all = [a + b for a, b in zip(lost_all, lost)]
        fails += bool(bad)
        print(f"  {'ok  ' if not bad else 'FAIL'}  {name}: {n} clocks, every output matches the model"
              if not bad else f"  FAIL  {name}: {bad} output mismatches in {n} clocks")
    silent = lost_all[2]
    fails += bool(silent)
    print(f"  {'ok  ' if not silent else 'FAIL'}  no pin event lost without overflow: "
          f"{lost_all[1]} dropped, all flagged ({silent} silent); "
          f"{lost_all[0]} delayed a clock by a TMARK, none lost")
    print(f"\n{len(SUITE) + 1} checks, {fails} failures")
    print("SYNC REFERENCE MODEL PASSED\n" if not fails else "SYNC REFERENCE MODEL FAILED\n")
    return fails


if __name__ == "__main__":
    if sys.argv[1:] == ["--suite"]:
        sys.exit(1 if suite() else 0)
    hdr, n, bad, lost = run(sys.argv[1])
    print(f"{n} clocks, {bad} output mismatches; {lost[1]} pin events dropped, "
          f"{lost[2]} of them silently; {lost[0]} delayed by a TMARK")
    sys.exit(1 if bad or lost[2] else 0)
