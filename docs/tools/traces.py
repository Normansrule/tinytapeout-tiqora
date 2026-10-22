#!/usr/bin/env python3
"""traces.py — the explorer's tour fixtures, cut from a real RTL simulation.

    python3 docs/tools/traces.py            run make -C test tour, write docs/site/data/traces/
    python3 docs/tools/traces.py --check    run it again and fail if any fixture differs
                                            (stale against the RTL, or not deterministic)

test/tb_tour.sv talks to the submitted top over its serial pins at 434 clocks
per bit and writes a line on every clock where a traced signal changes. This
script decodes every byte on both serial pins straight from the pin trace,
runs the host commands through an independent Python model of the protocol
in src/uart/tp_host_uart.sv, and stops without writing anything if a single
reply the chip sent differs from what the model predicts. Every caption is
anchored to a cycle found in the data, never a hand-typed cycle number.
"""
import os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tracekit as tk

OUT = "docs/site/data/traces"
DIV = 434
HSTATES = ["H_CMD", "H_ADDR", "H_DATA", "H_DO", "H_SEND"]
REGS = {0: "TIME", 1: "EVENT", 2: "STAT", 3: "CFG", 4: "CMP0", 5: "CMP1", 7: "PW", 8: "ADJ", 9: "RATE", 10: "PULSE"}
RTL = ["src/tp_pkg.sv", "src/sync/sync_timebase.sv", "src/sync/sync_capture.sv", "src/sync/sync_event_fifo.sv",
       "src/sync/sync_compare.sv", "src/sync/sync_unit.sv", "src/uart/tp_uart_rx.sv", "src/uart/tp_uart_tx.sv",
       "src/uart/tp_host_uart.sv", "src/tp_sync_soc.sv", "src/tt_um_normansrule_tiqora_serial.sv"]
BENCH = ["test/tb_tour.sv"]


def bit(col, n):
    return lambda r: None if r[col] is None else (r[col] >> n) & 1


def run_sim():
    r = subprocess.run(["make", "-s", "-C", "test", "tour"], capture_output=True, text=True)
    if r.returncode:
        sys.exit("traces.py: make -C test tour failed:\n" + r.stdout[-3000:] + r.stderr[-2000:])
    return r.stdout


def at_cycle(rows, cyc):
    """The traced values in force at cycle cyc (the trace only lists changes)."""
    cur = rows[0]
    for r in rows:
        if r["cycle"] > cyc:
            break
        cur = r
    return cur


def decode_uart(rows, fn):
    """Every 8N1 byte on a pin, sampled at bit centres from the change list: [(start, byte, stop_ok)]."""
    out, t = [], rows[0]["cycle"]
    last = rows[-1]["cycle"]
    edges = [r["cycle"] for i, r in enumerate(rows) if i and fn(r) == 0 and fn(rows[i - 1]) == 1 and r["rst_n"]]
    for s in edges:
        if s < t or s + 10 * DIV > last + DIV:
            continue
        v = lambda k: fn(at_cycle(rows, s + DIV // 2 + k * DIV))
        if v(0) != 0:
            continue
        b = sum(v(1 + i) << i for i in range(8))
        out.append((s, b, v(9) == 1))
        t = s + 9 * DIV + DIV // 2
    return out


def model(events):
    """An independent model of tp_host_uart: feed it host bytes and resets in
    time order, get back the reply each command must produce, and a meaning."""
    st, cmd, addr, data, out, cut = "CMD", None, None, [], [], []
    def cutoff():
        if st != "CMD":
            cut.append({"at": start, "cmd": f"{cmd} cut off after {len(seq)} of {6 if cmd == 'write' else 2} bytes", "bytes": seq, "reply": []})
    for kind, cyc, b in events:
        if kind == "reset":
            cutoff()
            st, cmd, data = "CMD", None, []
            continue
        if st == "CMD":
            if b == 0x01:
                st, cmd = "ADDR", "write"
            elif b == 0x02:
                st, cmd = "ADDR", "read"
            elif b == 0x03:
                out.append({"at": cyc, "cmd": "ping", "bytes": [b], "reply": [0x5A, 0x01]})
            else:
                out.append({"at": cyc, "cmd": f"unknown 0x{b:02X}", "bytes": [b], "reply": [0x15]})
            start = cyc
            if st == "ADDR":
                seq = [b]
        elif st == "ADDR":
            addr = b & 0xF
            seq.append(b)
            if cmd == "read":
                out.append({"at": start, "cmd": f"read {REGS.get(addr, addr)}", "addr": addr, "bytes": seq, "reply": "4 bytes"})
                st = "CMD"
            else:
                st, data = "DATA", []
        elif st == "DATA":
            data.append(b)
            seq.append(b)
            if len(data) == 4:
                v = sum(x << (8 * i) for i, x in enumerate(data))
                out.append({"at": start, "cmd": f"write {REGS.get(addr, addr)} = 0x{v:08X}", "addr": addr, "value": v, "bytes": seq, "reply": [0x06]})
                st = "CMD"
    cutoff()
    return out, cut


def main():
    check = "--check" in sys.argv
    log = run_sim()
    rows = tk.read_trace("test/tour_trace.txt")
    checks = tk.checks_from("test/tour_out.txt")
    if not checks or not all(c["ok"] for c in checks):
        sys.exit("traces.py: the tour testbench did not pass every check")
    prov = {"testbench": "test/tb_tour.sv",
            "command": "make -C test tour  (then python3 docs/tools/traces.py)",
            "simulator": tk.tool_version(["iverilog", "-V"]),
            "sources": {f: tk.sha(f) for f in RTL + BENCH},
            "sampling": "sampled on the falling edge of every clock; a line is kept only where a traced signal other than the timebase changes. Cycle 0 is the first rising edge after reset is released; reset holds the count. 1 cycle = 20 ns at 50 MHz; one serial bit is 434 cycles (115,200 baud)"}

    # ---------------------------------------------------------- bytes on the wire, checked
    rx = bit("ui_in", 3)
    tx = bit("uo_out", 4)
    host = decode_uart(rows, rx)
    chip = decode_uart(rows, tx)
    seen = [(r["cycle"], r["rx_data"]) for r in rows if r["rx_valid"] == 1]
    if [b for _, b, _ in host] != [b for _, b in seen]:
        sys.exit("traces.py: the bytes decoded from ui_in[3] differ from what tp_uart_rx delivered")
    resets = [r["cycle"] for i, r in enumerate(rows) if i and r["rst_n"] == 0 and rows[i - 1]["rst_n"] == 1]
    events = sorted([("byte", s, b) for s, b, _ in host] + [("reset", c, None) for c in resets], key=lambda e: (e[1], e[0] == "byte"))
    cmds, cut = model(events)
    if len(cut) != 1:
        sys.exit(f"traces.py: expected one cut-off command in the tour, the model found {len(cut)}")
    pending = cut[0]
    # pair each command with the chip bytes that follow it, before the next command or reset
    marks_at = sorted([c["at"] for c in cmds] + resets + ([pending["at"]] if pending else []))
    for c in cmds:
        nxt = min([m for m in marks_at if m > c["at"]] + [10 ** 12])
        got = [b for s, b, ok in chip if c["at"] < s < nxt]
        c["got"] = got
        if c["reply"] == "4 bytes":
            if len(got) != 4:
                sys.exit(f"traces.py: {c['cmd']} answered {len(got)} bytes, the model expects 4")
            c["value"] = sum(x << (8 * i) for i, x in enumerate(got))
        elif got != c["reply"]:
            sys.exit(f"traces.py: {c['cmd']} answered {got}, the model predicts {c['reply']}")
    if pending:
        nxt = min([m for m in resets if m > pending["at"]] + [10 ** 12])
        pending["got"] = [b for s, b, ok in chip if pending["at"] < s < nxt]
        if pending["got"]:
            sys.exit("traces.py: the chip answered a cut-off command; the model says it must stay silent")

    def lane(lo, hi):
        """Every byte in [lo, hi] for the byte lane under the waveform."""
        out = [{"at": s, "end": s + 10 * DIV, "dir": "host", "byte": b} for s, b, _ in host if lo <= s <= hi]
        out += [{"at": s, "end": s + 10 * DIV, "dir": "chip", "byte": b} for s, b, _ in chip if lo <= s <= hi]
        return sorted(out, key=lambda x: x["at"])

    def cmd_list(lo, hi):
        return [{k: v for k, v in c.items() if k != "reply" or v != "4 bytes"} for c in cmds + ([pending] if pending else []) if lo <= c["at"] <= hi]

    def find(prefix):
        return next(c for c in cmds if c["cmd"].startswith(prefix))

    def end_of(c):
        """Cycle the last reply byte's stop bit ends."""
        sb = [s for s, b, ok in chip if s > c["at"]][:len(c["got"])]
        return (sb[-1] if sb else c["at"]) + 10 * DIV

    def first_after(pred, after):
        return tk.first(rows, pred, after=after)

    base = [{"id": "rx", "label": "RX (ui_in[3])", "width": 1, "kind": "bit", "fn": rx, "block": "tp_uart_rx", "meaning": "serial in from the host, idle high"},
            {"id": "tx", "label": "TX (uo_out[4])", "width": 1, "kind": "bit", "fn": tx, "block": "tp_uart_tx", "meaning": "serial out to the host, idle high"},
            {"id": "act", "label": "ACT (uio[1])", "width": 1, "kind": "bit", "fn": lambda r: r["act"], "block": "tp_host_uart", "meaning": "a command or reply is in progress"},
            {"id": "h_state", "label": "host port state", "width": 3, "kind": "enum", "enum": HSTATES, "fn": lambda r: r["h_state"], "block": "tp_host_uart", "meaning": "tp_host_uart's state register"},
            {"id": "h_count", "label": "bytes left", "width": 3, "kind": "bus", "fn": lambda r: r["h_count"], "block": "tp_host_uart", "meaning": "bytes still to receive (H_DATA) or send (H_SEND)"},
            {"id": "rx_byte", "label": "byte received", "width": 8, "kind": "bus", "fn": lambda r: r["rx_data"] if r["rx_valid"] else None, "block": "tp_uart_rx", "meaning": "rx_data on the clock rx_valid pulses"},
            {"id": "reg_req", "label": "register access", "width": 1, "kind": "bit", "fn": lambda r: r["reg_req"], "block": "tp_host_uart", "meaning": "the single H_DO clock on the sync unit's register port"},
            {"id": "reg_addr", "label": "register", "width": 4, "kind": "enum", "enum": [REGS.get(i, f"offset {i}") for i in range(16)], "fn": lambda r: r["reg_addr"], "block": "tp_host_uart", "meaning": "register offset (tp_pkg.sv)"}]
    fixtures = []

    def hex_bytes(bs):
        return " ".join(f"{b:02X}" for b in bs)

    def cmd_caps(c, blocks=("tp_host_uart",)):
        """Captions for one command: its bytes arriving, the register clock, the reply."""
        caps = [{"at": c["at"], "text": f"Host sends {hex_bytes(c['bytes'])}: {c['cmd']}.", "blocks": ["tp_uart_rx", *blocks]}]
        do = [r["cycle"] for r in rows if r["reg_req"] == 1 and c["at"] < r["cycle"] < end_of(c)]
        if do:
            caps.append({"at": do[0], "text": f"H_DO: one clock on the register port, offset {c.get('addr')} ({REGS.get(c.get('addr'), '?')}).", "blocks": ["tp_host_uart", "sync_unit"]})
        if c["got"]:
            s0 = next(s for s, b, ok in chip if s > c["at"])
            caps.append({"at": s0, "text": f"The chip answers {hex_bytes(c['got'])}" + (f", least significant byte first: 0x{c['value']:08X}." if "value" in c and c["reply"] == "4 bytes" else "."), "blocks": ["tp_uart_tx", "tp_host_uart"]})
        return caps

    # ---------------------------------------------------------- 1 ping and a write
    ping = cmds[0]
    wcfg = find("write CFG")
    lo, hi = ping["at"] - DIV, end_of(wcfg) + DIV
    caps = cmd_caps(ping) + cmd_caps(wcfg)
    caps[0]["text"] += " One byte: a start bit (low), eight data bits least significant first, a stop bit (high), 434 clocks each."
    st0 = first_after(lambda r: r["h_state"] == 4, ping["at"])
    caps.append({"at": st0, "text": "H_SEND with 2 bytes to go: 0x5A (the magic) and 0x01 (the version). The reply is shifted out of the same 32-bit register that collects write data.", "blocks": ["tp_host_uart"]})
    dat = first_after(lambda r: r["h_state"] == 2, wcfg["at"])
    caps.append({"at": dat, "text": "H_DATA: four data bytes to collect, least significant first; each one shifts in at the top of the register.", "blocks": ["tp_host_uart"]})
    fixtures.append(tk.fixture("host-protocol", "Ping, then a register write",
        "The whole host protocol in two commands: a ping and its two-byte answer, then a six-byte write that configures capture and is ACKed.",
        rows, lo, hi, base, caps, [{"at": wcfg["at"], "label": "write"}],
        [c for c in checks if c["text"].startswith("ping") or "CFG" in c["text"]], prov,
        {"bytes": lane(lo, hi), "commands": cmd_list(lo, hi),
         "protocol": {"write": "01 addr d0 d1 d2 d3 -> 06", "read": "02 addr -> d0 d1 d2 d3", "ping": "03 -> 5A 01",
                      "other": "anything else -> 15 (NAK)", "byte_order": "least significant byte first", "framing": "8N1, 434 clocks per bit (115,200 baud at 50 MHz)",
                      "timeout": "none: a command cut off part way waits for its remaining bytes until reset", "source": "src/uart/tp_host_uart.sv header"}}))

    # ---------------------------------------------------------- 2 read TIME
    rt = find("read TIME")
    do = first_after(lambda r: r["reg_req"] == 1, rt["at"])
    now_do = at_cycle(rows, do)["now"]
    if rt["value"] != now_do:
        sys.exit(f"traces.py: read TIME returned 0x{rt['value']:08X}; the timebase at the H_DO clock was 0x{now_do:08X}")
    lo, hi = rt["at"] - DIV, end_of(rt) + DIV
    caps = cmd_caps(rt, ("sync_timebase",))
    caps[1]["text"] += f" The timebase reads {now_do} at this clock, and that exact value is what goes back."
    caps.append({"at": end_of(rt) - 10 * DIV, "text": f"Four bytes have gone out; the host reassembles them, lowest first. By the time the last stop bit ends, {end_of(rt) - do} clocks after the read, the timebase has moved on: the answer is a timestamp of the read, not of the moment it arrives.", "blocks": ["sync_timebase"]})
    fixtures.append(tk.fixture("read-time", "Reading the timebase",
        "A two-byte read and its four-byte answer, least significant byte first: the value is the timebase on the one clock the port touched the register.",
        rows, lo, hi, base + [{"id": "now", "label": "timebase", "width": 32, "kind": "bus", "fn": lambda r: r["now"], "block": "sync_timebase", "meaning": "sync_timebase now, at each traced change"}],
        caps, [{"at": do, "label": "H_DO"}],
        [c for c in checks if "TIME" in c["text"] and "CMP0" not in c["text"]], prov,
        {"bytes": lane(lo, hi), "commands": cmd_list(lo, hi)}))

    # ---------------------------------------------------------- 3 deadline
    wc = find("write CMP0")
    arm = first_after(lambda r: r["armed"] is not None and r["armed"] & 1, wc["at"])
    rise = first_after(lambda r: r["uo_out"] is not None and r["uo_out"] & 1, arm)
    fall = first_after(lambda r: r["uo_out"] is not None and not r["uo_out"] & 1, rise)
    rr = at_cycle(rows, rise)
    if rr["now"] != rr["deadline0"] or rr["deadline0"] != wc["value"] or wc["value"] != rt["value"] + 60000:
        sys.exit("traces.py: TRIG0 did not rise on the written deadline tick")
    lo, hi = wc["at"] - DIV, fall + 4 * DIV
    caps = cmd_caps(wc, ("sync_compare",))
    caps.append({"at": arm, "text": f"armed[0] goes high on the H_DO clock: channel 0 now waits for tick {wc['value']} (the TIME read + 60000).", "blocks": ["sync_compare"]})
    caps.append({"at": rise, "text": f"Tick {rr['now']}: TRIG0 (uo_out[0]) rises on exactly the deadline tick. No host is involved; the ACK went out long ago.", "blocks": ["sync_compare"]})
    caps.append({"at": fall, "text": f"TRIG0 falls {fall - rise} ticks later: the default pulse width of 8. armed[0] cleared when it fired, so it fires once.", "blocks": ["sync_compare"]})
    fixtures.append(tk.fixture("deadline", "A deadline set over serial",
        "Write CMP0 over the serial port and the trigger pin rises on exactly that tick, 8 ticks wide, with nothing on the wire.",
        rows, lo, hi, base + [
            {"id": "now", "label": "timebase", "width": 32, "kind": "bus", "fn": lambda r: r["now"], "block": "sync_timebase", "meaning": "sync_timebase now, at each traced change"},
            {"id": "deadline0", "label": "deadline 0", "width": 32, "kind": "bus", "fn": lambda r: r["deadline0"], "block": "sync_compare", "meaning": "the armed tick"},
            {"id": "armed0", "label": "armed 0", "width": 1, "kind": "bit", "fn": bit("armed", 0), "block": "sync_compare", "meaning": "channel 0 armed"},
            {"id": "trig0", "label": "TRIG0 (uo_out[0])", "width": 1, "kind": "bit", "fn": bit("uo_out", 0), "block": "sync_compare", "meaning": "trigger pin"}],
        caps, [{"at": rise, "label": "deadline tick"}],
        [c for c in checks if "CMP0" in c["text"] or "TRIG0" in c["text"]], prov,
        {"bytes": lane(lo, hi), "commands": cmd_list(lo, hi)}))

    # ---------------------------------------------------------- 4 capture and read EVENT
    re_ = find("read EVENT")
    edge = first_after(lambda r: r["ui_in"] is not None and r["ui_in"] & 1, fall)
    evtp = first_after(lambda r: r["uo_out"] is not None and r["uo_out"] >> 7 & 1, edge)
    evq = first_after(lambda r: r["evq"] == 1, edge)
    do = first_after(lambda r: r["reg_req"] == 1, re_["at"])
    gone = first_after(lambda r: r["evq"] == 0, do - 1)
    v = re_["value"]
    lo, hi = edge - 2 * DIV, end_of(re_) + DIV
    caps = [{"at": edge, "text": "CAP0 (ui_in[0]) rises. Capture is enabled for channel 0, rising edges (the CFG write in the first tour).", "blocks": ["sync_capture"]},
            {"at": evtp, "text": f"{evtp - edge} clocks later the edge is through the two-flop synchronizer and the edge detector: EVTP pulses for one clock and EVT goes high.", "blocks": ["sync_capture", "sync_unit"]},
            {"at": evq, "text": "The board can see the event without asking: EVQ = 1 (one queued), EVCH = 0, EVED = 1 (rising) on the uio pins.", "blocks": ["sync_event_fifo", "tt_um_normansrule_tiqora_serial"]}]
    caps += cmd_caps(re_, ("sync_event_fifo",))
    caps.append({"at": gone, "text": f"Reading EVENT pops the queue on the H_DO clock: EVQ and EVT drop. The word is source {v >> 31} (pin), channel {(v >> 28) & 7}, {'rising' if (v >> 27) & 1 else 'falling'}, timestamp {v & 0x7FFFFFF}.", "blocks": ["sync_event_fifo"]})
    fixtures.append(tk.fixture("event", "An edge, queued and read",
        "An edge on a capture pin becomes a timestamped event: the queue pins show it at once, and a serial read pops it.",
        rows, lo, hi, base + [
            {"id": "cap0", "label": "CAP0 (ui_in[0])", "width": 1, "kind": "bit", "fn": bit("ui_in", 0), "block": "sync_capture", "meaning": "capture input 0"},
            {"id": "evtp", "label": "EVTP (uo_out[7])", "width": 1, "kind": "bit", "fn": bit("uo_out", 7), "block": "sync_unit", "meaning": "one-clock pulse per captured event"},
            {"id": "evt", "label": "EVT (uo_out[3])", "width": 1, "kind": "bit", "fn": bit("uo_out", 3), "block": "sync_unit", "meaning": "queue not empty"},
            {"id": "evq", "label": "EVQ (uio[7:6])", "width": 2, "kind": "bus", "fn": lambda r: r["evq"], "block": "sync_event_fifo", "meaning": "events in the queue"},
            {"id": "evch", "label": "EVCH (uio[4:2])", "width": 3, "kind": "bus", "fn": lambda r: r["evch"], "block": "sync_event_fifo", "meaning": "channel of the queue head; undefined until the first event"},
            {"id": "eved", "label": "EVED (uio[5])", "width": 1, "kind": "bit", "fn": lambda r: r["eved"], "block": "sync_event_fifo", "meaning": "edge of the queue head, 1 = rising"}],
        caps, [{"at": evtp, "label": "captured"}, {"at": gone, "label": "popped"}],
        [c for c in checks if "CAP0" in c["text"] or "EVENT" in c["text"]], prov,
        {"bytes": lane(lo, hi), "commands": cmd_list(lo, hi),
         "event_format": {"31": "source: 0 pin, 1 TMARK", "30:28": "channel or tag", "27": "1 = rising edge", "26:0": "timestamp, low 27 bits of the timebase"}}))

    # ---------------------------------------------------------- 5 errors and recovery
    nak = next(c for c in cmds if c["cmd"].startswith("unknown"))
    rst = next(c for c in resets if c > pending["at"])
    after = [c for c in cmds if c["at"] > rst]
    lo, hi = nak["at"] - DIV, end_of(after[0]) + DIV
    cut_bytes = [(s, b) for s, b, _ in host if pending["at"] <= s < rst]
    if [b for _, b in cut_bytes] != [0x01, 0x07, 0x20, 0x03]:
        sys.exit("traces.py: the cut-off write in the tour is not 01 07 20 then a ping")
    swallowed = [cut_bytes[3][0]]
    caps = cmd_caps(nak)
    caps[-1]["text"] = "The chip answers 15, NAK: not a command it knows. The port is back in H_CMD and nothing else changed."
    caps.append({"at": pending["at"], "text": f"Host sends {hex_bytes(pending['bytes'][:3])}: a write cut off after its address and one data byte. The port is in H_DATA with 3 bytes to go, and it has no timeout.", "blocks": ["tp_host_uart"]})
    if swallowed:
        caps.append({"at": swallowed[0], "text": "The host gives up and pings (03). The port takes it as the second data byte: no reply. A host that loses sync sees silence, not an error.", "blocks": ["tp_host_uart"]})
    caps.append({"at": rst, "text": "Reset (rst_n low) is the only thing that clears it. The rest of the chip resets too: timebase, queue and comparators.", "blocks": ["tt_um_normansrule_tiqora_serial", "tp_host_uart"]})
    caps += cmd_caps(after[0])
    caps[-1]["text"] = "After reset the ping answers 5A 01 again."
    fixtures.append(tk.fixture("errors", "Wrong bytes, and the way out",
        "An unknown command gets NAK; a command cut off part way gets nothing at all, swallows the next command, and only reset recovers.",
        rows, lo, hi, [{"id": "rst_n", "label": "rst_n", "width": 1, "kind": "bit", "fn": lambda r: r["rst_n"], "block": "tt_um_normansrule_tiqora_serial", "meaning": "reset pin, active low"}] + base,
        caps, [{"at": rst, "label": "reset"}],
        [c for c in checks if any(k in c["text"] for k in ("NAK", "truncated", "data byte", "after reset"))], prov,
        {"bytes": lane(lo, hi), "commands": cmd_list(lo, hi)}))

    # ---------------------------------------------------------- overview
    last = rows[-1]["cycle"]
    caps = [{"at": c["at"], "text": c["cmd"] + (f" -> {hex_bytes(c['got'])}" if c["got"] else " -> no reply"), "blocks": ["tp_host_uart"]} for c in cmds]
    caps.append({"at": pending["at"], "text": pending["cmd"] + ": no reply", "blocks": ["tp_host_uart"]})
    caps.append({"at": rise, "text": "TRIG0 on the deadline tick", "blocks": ["sync_compare"]})
    caps.append({"at": evtp, "text": "CAP0 edge captured", "blocks": ["sync_capture"]})
    caps.append({"at": rst, "text": "reset", "blocks": ["tt_um_normansrule_tiqora_serial"]})
    fixtures.append(tk.fixture("overview", "The whole serial session",
        "Every byte the host and the chip exchanged in the tour, each command decoded and checked against a model of the protocol.",
        rows, rows[0]["cycle"], last,
        [{"id": "rst_n", "label": "rst_n", "width": 1, "kind": "bit", "fn": lambda r: r["rst_n"], "block": "tt_um_normansrule_tiqora_serial", "meaning": "reset pin"}] + base[:4] +
        [{"id": "trig0", "label": "TRIG0", "width": 1, "kind": "bit", "fn": bit("uo_out", 0), "block": "sync_compare", "meaning": "uo_out[0]"},
         {"id": "evt", "label": "EVT", "width": 1, "kind": "bit", "fn": bit("uo_out", 3), "block": "sync_unit", "meaning": "uo_out[3]"}],
        caps, [], checks, prov,
        {"bytes": lane(rows[0]["cycle"], last), "commands": cmd_list(rows[0]["cycle"], last)}))

    texts = tk.write_all(fixtures, OUT, {"chip": "Tiqora-Serial", "tour_checks": len(checks), "model": "every chip reply checked against a Python model of the src/uart/tp_host_uart.sv protocol"})
    bad = tk.compare_or_write(texts, check)
    if check:
        for b in bad:
            print("  differs: " + b)
        print(f"traces: {len(fixtures)} fixtures from {len(checks)} passing testbench checks, " +
              ("identical to a fresh simulation" if not bad else f"{len(bad)} files differ: run python3 docs/tools/traces.py"))
        sys.exit(1 if bad else 0)
    print(f"wrote {len(texts)} files to {OUT}")


if __name__ == "__main__":
    main()
