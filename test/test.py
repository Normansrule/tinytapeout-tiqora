import os
# test.py — cocotb tests for Tiqora-Serial.
#
# These drive the chip the way the demo board does: a serial line into
# ui_in[3] and a serial line out of uo_out[4], plus the capture pins. No
# hierarchy peeking except one probe of the timebase, which is the only
# way to check a tick-exact claim from outside.
#
# Positional time units, not units=/unit=, because the keyword was renamed
# in cocotb 2.0 and the positional form works on both 1.x and 2.x.

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles, Timer, First, Edge, ReadOnly

CLK_NS = 20                 # 50 MHz
DIV    = 434                # clocks per serial bit, fixed in the silicon
BIT_NS = DIV * CLK_NS       # 8.68 us -> 115200 baud

RX_BIT = 3                  # ui_in[3]
TX_BIT = 4                  # uo_out[4]

CMD_WRITE, CMD_READ, CMD_PING = 0x01, 0x02, 0x03
RSP_ACK, RSP_NAK, RSP_MAGIC = 0x06, 0x15, 0x5A
REG_TIME, REG_EVENT, REG_STAT, REG_CFG = 0, 1, 2, 3
REG_CMP0, REG_PW, REG_PULSE = 4, 7, 10


def set_rx(dut, level):
    v = int(dut.ui_in.value)
    dut.ui_in.value = (v | (1 << RX_BIT)) if level else (v & ~(1 << RX_BIT))


def get_tx(dut):
    return (int(dut.uo_out.value) >> TX_BIT) & 1


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, "ns").start())
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = 1 << RX_BIT          # serial idles high
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 10)


async def send_byte(dut, b):
    set_rx(dut, 0)                          # start bit
    await Timer(BIT_NS, "ns")
    for i in range(8):
        set_rx(dut, (b >> i) & 1)           # least significant bit first
        await Timer(BIT_NS, "ns")
    set_rx(dut, 1)                          # stop bit
    await Timer(BIT_NS, "ns")


async def recv_byte(dut, timeout_bits=40):
    """Wait for a start bit and collect one byte."""
    waited = 0.0
    while get_tx(dut) == 1:
        await Timer(BIT_NS / 8, "ns")
        waited += 0.125
        if waited > timeout_bits:
            raise TimeoutError("no serial reply from the chip")
    await Timer(BIT_NS * 1.5, "ns")         # into the centre of bit 0
    b = 0
    for i in range(8):
        b |= get_tx(dut) << i
        await Timer(BIT_NS, "ns")
    return b


async def host_read(dut, addr):
    await send_byte(dut, CMD_READ)
    await send_byte(dut, addr)
    v = 0
    for i in range(4):
        v |= (await recv_byte(dut)) << (8 * i)
    return v


async def host_write(dut, addr, value):
    await send_byte(dut, CMD_WRITE)
    await send_byte(dut, addr)
    for i in range(4):
        await send_byte(dut, (value >> (8 * i)) & 0xFF)
    ack = await recv_byte(dut)
    assert ack == RSP_ACK, f"write to {addr} not acknowledged: 0x{ack:02X}"


GL = os.environ.get("GATES") == "yes"   # no internal hierarchy after hardening


@cocotb.test()
async def test_ping(dut):
    """The link answers and identifies itself."""
    await reset(dut)
    await send_byte(dut, CMD_PING)
    assert await recv_byte(dut) == RSP_MAGIC, "wrong magic byte"
    assert await recv_byte(dut) == 0x01, "wrong protocol version"


@cocotb.test()
async def test_bad_command_nak(dut):
    """Garbage is refused rather than misinterpreted."""
    await reset(dut)
    await send_byte(dut, 0xFF)
    assert await recv_byte(dut) == RSP_NAK


@cocotb.test()
async def test_timebase_runs(dut):
    """The timebase advances, and reads decode little endian."""
    await reset(dut)
    a = await host_read(dut, REG_TIME)
    await ClockCycles(dut.clk, 2000)
    b = await host_read(dut, REG_TIME)
    assert b > a, f"timebase did not advance: {a} then {b}"


@cocotb.test()
async def test_capture_over_serial(dut):
    """An edge on a capture pin comes back as a decoded event."""
    await reset(dut)
    await host_write(dut, REG_CFG, 0x0000_00FF)     # all channels, rising

    dut.ui_in.value = int(dut.ui_in.value) | (1 << 0)   # CAP0 rises
    await ClockCycles(dut.clk, 20)

    st = await host_read(dut, REG_STAT)
    assert (st & 0xF) >= 1, f"no event queued, status 0x{st:08X}"

    ev = await host_read(dut, REG_EVENT)
    assert (ev >> 31) == 0, "event should be a hardware capture"
    assert ((ev >> 28) & 7) == 0, "event should be on channel 0"
    assert ((ev >> 27) & 1) == 1, "event should be a rising edge"

    st = await host_read(dut, REG_STAT)
    assert (st >> 4) & 1, "reading the event register should have popped it"


@cocotb.test(skip=GL)   # reads the internal timebase; pins-only in GL runs
async def test_trigger_lands_on_exact_tick(dut):
    """The claim the chip exists for, driven entirely over serial.

    The deadline has to be far enough ahead that the six-byte serial write
    that arms it completes first: one byte is ten bits of 434 clocks, so
    arming costs about 26,000 clocks. A deadline 20,000 ticks out has
    already passed by the time the chip receives it.
    """
    await reset(dut)
    await host_write(dut, REG_PW, 200)

    now = await host_read(dut, REG_TIME)
    deadline = (now + 400_000) & 0xFFFFFFFF          # ~8 ms at 50 MHz
    await host_write(dut, REG_CMP0, deadline)

    tb = dut.user_project.u_soc.u_sync.now
    prev = int(dut.uo_out.value) & 1
    fired_at = None

    # uo_out is static while we wait, so waiting on any change is far
    # cheaper than stepping the clock 400,000 times
    for _ in range(64):
        await First(Edge(dut.uo_out), Timer(1, "ms"))
        await ReadOnly()
        cur = int(dut.uo_out.value) & 1
        if cur and not prev:
            fired_at = int(tb.value)
            break
        prev = cur
        await RisingEdge(dut.clk)

    assert fired_at is not None, "trigger never fired"
    assert fired_at == deadline, \
        f"fired at tick {fired_at}, programmed for {deadline}"
