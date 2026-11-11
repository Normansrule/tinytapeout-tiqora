// tp_host_uart.sv — the host port. This is what makes the 1x1 tile usable.
//
// Without a core there is nothing on the chip to configure the sync unit or
// read a timestamp back. This module is the missing piece: a serial port
// that reaches the same register interface the bus drives in the full chip.
//
// "Programmed over USB-C like an ESP32" means exactly what it means for an
// ESP32 devkit: a USB-to-UART bridge presents a serial port on the host and
// drives two pins on the chip. On the Tiny Tapeout demo board that bridge
// is the onboard RP2040, and the pins are the Tiny Tapeout recommended UART
// pins, so no external adapter is needed.
//
// Wire protocol, least significant byte first throughout:
//
//   host -> chip                          chip -> host
//   ------------------------------------  ---------------------------
//   0x01 addr d0 d1 d2 d3   write         0x06                   ACK
//   0x02 addr               read          d0 d1 d2 d3
//   0x03                    ping          0x5A ver         magic, version
//   anything else                         0x15                   NAK
//
// `addr` is a sync register offset, 0 to 10 (see tp_pkg.sv). Reading offset
// 1 pops the event queue, exactly as it does from the core in the full chip.
//
// Frame timeout: if the line goes quiet for 2^TOW clocks in the middle of a
// command (after its first byte, before its last), the partial frame is
// thrown away and the port waits for a command byte again. Without it, a
// host that stopped mid-frame left the port waiting, and the next command's
// bytes completed the old frame: a cut write followed by a good one wrote
// garbage. At 50 MHz, TOW = 20 is 21 ms, far longer than any gap a USB serial
// bridge leaves inside a frame and short enough that a host retrying after an
// error is never confused.
//
// Area: one 32-bit register carries the write data in and the read data
// out, because the two are never live at the same time. The register port
// is driven combinationally during the single H_DO cycle, so it needs no
// registers of its own either.
`default_nettype none

module tp_host_uart #(
    parameter int  DIV     = 434,
    parameter int  DIVW    = 9,
    parameter int  TOW     = 20,          // frame timeout: 2^TOW clocks of silence
    parameter logic [7:0] VERSION = 8'h01
) (
    input  wire  logic        clk,
    input  wire  logic        rst,

    input  wire  logic        rx_pin,
    output logic              tx_pin,

    output logic              reg_req,
    output logic [3:0]        reg_addr,
    output logic              reg_we,
    output logic [31:0]       reg_wdata,
    input  wire  logic [31:0] reg_rdata,

    output logic              active
);

    localparam logic [7:0] CMD_WRITE = 8'h01;
    localparam logic [7:0] CMD_READ  = 8'h02;
    localparam logic [7:0] CMD_PING  = 8'h03;
    localparam logic [7:0] RSP_ACK   = 8'h06;
    localparam logic [7:0] RSP_NAK   = 8'h15;
    localparam logic [7:0] RSP_MAGIC = 8'h5A;

    localparam logic [2:0] H_CMD   = 3'd0;   // waiting for a command byte
    localparam logic [2:0] H_ADDR  = 3'd1;   // waiting for the address
    localparam logic [2:0] H_DATA  = 3'd2;   // collecting 4 write bytes
    localparam logic [2:0] H_DO    = 3'd3;   // one cycle on the register port
    localparam logic [2:0] H_SEND  = 3'd4;   // shifting the reply out

    logic [7:0] rx_data;
    logic       rx_valid;

    tp_uart_rx #(.DIV(DIV), .DIVW(DIVW)) u_rx (
        .clk(clk), .rst(rst), .rx_pin(rx_pin),
        .data(rx_data), .valid(rx_valid)
    );

    logic [2:0]  state;
    logic [31:0] payload;     // write data in, reply out: never both at once
    logic [2:0]  count;       // bytes left to receive or to send
    logic        is_write;
    logic        tx_busy, tx_go;

    // A byte is launched combinationally, so the transmitter captures
    // payload[7:0] in the same cycle the payload shifts down — no separate
    // transmit-data register.
    assign tx_go = (state == H_SEND) && (count != 3'd0) && !tx_busy;

    tp_uart_tx #(.DIV(DIV), .DIVW(DIVW)) u_tx (
        .clk(clk), .rst(rst), .start(tx_go), .data(payload[7:0]),
        .tx_pin(tx_pin), .busy(tx_busy)
    );

    // Register port: live only during H_DO, driven straight from state.
    assign reg_req   = (state == H_DO);
    assign reg_we    = is_write;
    assign reg_wdata = payload;

    assign active = (state != H_CMD) || tx_busy;

    // Clocks since the last byte while a frame is half received. Saturating
    // at all ones is the timeout; anything other than waiting for a frame's
    // next byte holds it at zero.
    logic [TOW-1:0] idle;
    logic           timeout;
    assign timeout = &idle;
    always_ff @(posedge clk) begin
        if (rst || rx_valid || !(state == H_ADDR || state == H_DATA)) idle <= '0;
        else                                                          idle <= idle + 1'b1;
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            state    <= H_CMD;
            payload  <= 32'd0;
            count    <= 3'd0;
            is_write <= 1'b0;
            reg_addr <= 4'd0;
        end else begin
            unique case (state)

                H_CMD: begin
                    if (rx_valid) begin
                        unique case (rx_data)
                            CMD_WRITE: begin
                                is_write <= 1'b1;
                                state    <= H_ADDR;
                            end
                            CMD_READ: begin
                                is_write <= 1'b0;
                                state    <= H_ADDR;
                            end
                            CMD_PING: begin
                                payload <= {16'd0, VERSION, RSP_MAGIC};
                                count   <= 3'd2;
                                state   <= H_SEND;
                            end
                            default: begin
                                payload <= {24'd0, RSP_NAK};
                                count   <= 3'd1;
                                state   <= H_SEND;
                            end
                        endcase
                    end
                end

                H_ADDR: begin
                    if (rx_valid) begin
                        reg_addr <= rx_data[3:0];
                        count    <= 3'd4;
                        state    <= is_write ? H_DATA : H_DO;
                    end else if (timeout) begin
                        state    <= H_CMD;          // cut frame: drop it
                    end
                end

                H_DATA: begin
                    if (rx_valid) begin
                        // least significant byte arrives first, so shift
                        // each new byte in at the top
                        payload <= {rx_data, payload[31:8]};
                        count   <= count - 3'd1;
                        if (count == 3'd1) state <= H_DO;
                    end else if (timeout) begin
                        state   <= H_CMD;           // cut frame: nothing is written
                    end
                end

                H_DO: begin
                    // The access happens combinationally in this cycle; a
                    // read of tp_pkg::SR_EVENT pops the queue at this clock edge,
                    // after its head has been captured here.
                    if (is_write) begin
                        payload <= {24'd0, RSP_ACK};
                        count   <= 3'd1;
                    end else begin
                        payload <= reg_rdata;
                        count   <= 3'd4;
                    end
                    state <= H_SEND;
                end

                H_SEND: begin
                    if (tx_go) begin
                        payload <= {8'd0, payload[31:8]};
                        count   <= count - 3'd1;
                    end else if (count == 3'd0 && !tx_busy) begin
                        state <= H_CMD;
                    end
                end

                default: state <= H_CMD;
            endcase
        end
    end

endmodule : tp_host_uart
