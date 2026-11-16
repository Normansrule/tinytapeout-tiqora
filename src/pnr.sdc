# Place-and-route constraints (tape-out audit experiment, 2026-11-16).
# LibreLane's default constraints, with a tighter edge-rate target for the
# resizer and clock-tree steps only: 0.5 ns instead of 0.75 ns. Signoff
# timing still reads the default file (SIGNOFF_SDC_FILE is not set), so the
# 0.75 ns limit that the signoff audit checks is unchanged.
source $::env(SCRIPTS_DIR)/base.sdc
set_max_transition 0.5 [current_design]
