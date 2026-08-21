# Golden Dataset — Schematic Crop Review MVP

This directory holds the golden dataset of cropped schematic PNG/JPG images used for evaluating component, value, pin, connectivity, section classification, and false FAIL metrics.

## Evaluation Categories
1. **VDDP / Power Supply Decoupling**: Crops containing TLE987x power pins, decoupling capacitors (e.g. 100 nF, 1 uF), GND connections.
2. **LIN Bus Physical Interface**: Crops containing LIN pin, ESD protection diodes, termination resistors.
3. **Crystal Oscillator**: Crops showing XTAL1, XTAL2 pins, load capacitors, crystal resonator.
4. **Bridge Driver Stage**: Crops showing SH1, GH1, GL1 gate driver pins and half-bridge MOSFET topologies.
5. **Partial / Cutoff Crops**: Ambiguous crops with wire terminations cut off by crop borders (verifying `INSUFFICIENT_INPUT` handling).

## File Naming Convention
- `vddp_decoupling_01.png`
- `lin_interface_01.png`
- `xtal_oscillator_01.png`
- `bridge_driver_01.png`
- `cutoff_ambiguous_01.png`
