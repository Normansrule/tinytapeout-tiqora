// caravel_gpio_modes.vh — Caravel GPIO power-on mode values, copied verbatim from
// efabless/caravel_user_project f534826 verilog/rtl/user_defines.v (Apache-2.0).
`define GPIO_MODE_INVALID                  13'hXXXX
`define GPIO_MODE_MGMT_STD_INPUT_NOPULL    13'h0403
`define GPIO_MODE_MGMT_STD_INPUT_PULLDOWN  13'h0c01
`define GPIO_MODE_MGMT_STD_INPUT_PULLUP    13'h0801
`define GPIO_MODE_MGMT_STD_OUTPUT          13'h1809
`define GPIO_MODE_MGMT_STD_BIDIRECTIONAL   13'h1801
`define GPIO_MODE_MGMT_STD_ANALOG          13'h000b
`define GPIO_MODE_USER_STD_INPUT_NOPULL    13'h0402
`define GPIO_MODE_USER_STD_INPUT_PULLDOWN  13'h0c00
`define GPIO_MODE_USER_STD_INPUT_PULLUP    13'h0800
`define GPIO_MODE_USER_STD_OUTPUT          13'h1808
`define GPIO_MODE_USER_STD_BIDIRECTIONAL   13'h1800
`define GPIO_MODE_USER_STD_OUT_MONITORED   13'h1802
`define GPIO_MODE_USER_STD_ANALOG          13'h000a
