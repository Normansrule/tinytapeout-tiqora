# Place-and-route constraints (tape-out audit experiment, 2026-11-16).
# LibreLane's default constraints with a lower fanout target (7) for the
# resizer and clock-tree steps only, so weak drivers get fewer loads each.
# Signoff still reads the default file (SIGNOFF_SDC_FILE is not set), so the
# limits the signoff audit checks (fanout 10, edge rate 0.75 ns) are unchanged.
source $::env(SCRIPTS_DIR)/base.sdc
set_max_fanout 7 [current_design]
