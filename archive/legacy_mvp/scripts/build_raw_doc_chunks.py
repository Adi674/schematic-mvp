"""
Script to format PDF OCR text into structured section chunks for Chroma RAG indexing.
"""

import os
import json


def generate_doc_chunks():
    chunks = [
        {
            "chunk_id": "chunk_ch1_overview",
            "chapter_num": 1,
            "chapter_name": "TLE987x/6x family",
            "domain": "OVERVIEW",
            "title": "TLE987x/6x family overview and block diagram",
            "text": "The TLE987x/6x is a single-chip 3-phase/2-phase motor driver that integrates the industry standard Arm Cortex-M3 core, enabling implementation of advanced motor control algorithms like FOC. It includes NFET drivers, integrated charge pump, current sense amplifier, 10-bit ADC1, 8-bit ADC2, and optional 14-bit SDADC (TLE987x-2QX)."
        },
        {
            "chunk_id": "chunk_ch2_vpre",
            "chapter_num": 2,
            "chapter_name": "Power supply generation unit (PGU)",
            "domain": "PGU",
            "title": "Input voltage VS and pre-regulator VPRE",
            "text": "The VS input is the supply voltage derived from battery voltage (VBAT) protected by reverse battery diode D_VS. Pre-regulator VPRE generates internal 7V. Max current I_PRE = 110mA shared between VDDP and VDDEXT (I_PRE = I_DDP + I_DDEXT). VAREF reference voltage capacitor C_VAREF is 100nF up to 1uF."
        },
        {
            "chunk_id": "chunk_ch2_table4",
            "chapter_num": 2,
            "chapter_name": "Power supply generation unit (PGU)",
            "domain": "PGU",
            "title": "Component selection for VS pin (Table 4)",
            "text": "Table 4: VS pin components. Filter capacitor C_VS1 min value 100nF type X7R. Bulk capacitor C_VS2 min value 2.2uF type X7R. Diode D_VS for reverse battery protection."
        },
        {
            "chunk_id": "chunk_ch2_table5",
            "chapter_num": 2,
            "chapter_name": "Power supply generation unit (PGU)",
            "domain": "PGU",
            "title": "VDDP voltage regulator 5.0 V (Table 5)",
            "text": "Table 5: VDDP output capacitor C_VDDP. Ceramic capacitor min value: 470 nF + 1 uF (1.47 uF) type X7R. Max value: 2.2 uF + 2.2 uF (4.4 uF) type X7R. Voltage rating: 10 V or higher. Must be placed close to VDDP pin."
        },
        {
            "chunk_id": "chunk_ch2_table6",
            "chapter_num": 2,
            "chapter_name": "Power supply generation unit (PGU)",
            "domain": "PGU",
            "title": "VDDC voltage regulator 1.5 V (Table 6)",
            "text": "Table 6: VDDC output capacitor C_VDDC. Ceramic capacitor min value: 100 nF + 330 nF (430 nF) type X7R. Max value: 1 uF + 1 uF (2 uF) type X7R. Voltage rating: 4 V or higher."
        },
        {
            "chunk_id": "chunk_ch2_table7",
            "chapter_num": 2,
            "chapter_name": "Power supply generation unit (PGU)",
            "domain": "PGU",
            "title": "VDDEXT voltage regulator 5.0 V (Table 7)",
            "text": "Table 7: VDDEXT output capacitor C_VDDEXT. Ceramic capacitor min value: 100 nF + 1 uF (1.1 uF) type X7R. Max value: 2.2 uF + 2.2 uF (4.4 uF) type X7R. Voltage rating: 10 V or higher."
        },
        {
            "chunk_id": "chunk_ch3_table8",
            "chapter_num": 3,
            "chapter_name": "Clock generation unit (CGU)",
            "domain": "CLOCK",
            "title": "External Crystal mode and oscillator load caps (Table 8)",
            "text": "Table 8: Oscillator load capacitors C_XTAL1, C_XTAL2. For 4MHz: 33pF, 8MHz: 18pF, 12MHz: 12pF, 16MHz: 12pF. Recommended >= 10V ceramic capacitor X7R/X8R (0805 package). Serial damping resistor R_XTAL2 is 0-280 Ohm."
        },
        {
            "chunk_id": "chunk_ch4_table10",
            "chapter_num": 4,
            "chapter_name": "General purpose inputs outputs (GPIO)",
            "domain": "GPIO",
            "title": "Resistor selection for GPIOs (Table 10)",
            "text": "Table 10: Pull-up resistor R_PU for external pin termination = 10 kOhm. Serial resistor R_IO for high speed communication min value 220 Ohm to suppress signal ringing."
        },
        {
            "chunk_id": "chunk_ch5_lin",
            "chapter_num": 5,
            "chapter_name": "LIN transceiver",
            "domain": "LIN",
            "title": "LIN transceiver external components",
            "text": "Recommended 220 pF capacitor C_LIN between LIN and GND_LIN. GND_LIN connected to global ECU ground. Pull-up resistor between LIN and battery input >= 1 kOhm when using PWM."
        },
        {
            "chunk_id": "chunk_ch6_table11",
            "chapter_num": 6,
            "chapter_name": "High-voltage monitor input (MON)",
            "domain": "MON",
            "title": "Component selection for MON pin (Table 11)",
            "text": "Table 11: Dedicated R-C filter for MON pin. Filter resistor R_MON min value 1 kOhm (1206 SMD recommended). Filter capacitor C_MON ceramic min value 10 nF, typical voltage rating 50 V."
        },
        {
            "chunk_id": "chunk_ch7_table13",
            "chapter_num": 7,
            "chapter_name": "Analog to digital converters (ADC1)",
            "domain": "ADC",
            "title": "Component selection for ADC1 (Table 13)",
            "text": "Table 13: Anti-aliasing filter for ADC1. Filter resistor R_ADC1IN min 1 Ohm, max 2 Ohm. Filter capacitor C_ADC1IN min 10 nF, max 470 nF."
        },
        {
            "chunk_id": "chunk_ch8_table15",
            "chapter_num": 8,
            "chapter_name": "Sigma-delta analog digital converters (ADC3/4)",
            "domain": "ADC",
            "title": "Component selection for SDADC (Table 15)",
            "text": "Table 15: Resolution filter resistor R_SINCOS = 1 kOhm. Resolution filter capacitor C_SINCOS min >= 80 nF (typically 100nF). HF decoupling capacitor C_HF min 2 pF type X7R, typical 470 pF type X7R."
        },
        {
            "chunk_id": "chunk_ch9_table",
            "chapter_num": 9,
            "chapter_name": "Bridge driver (excluding charge pump)",
            "domain": "BRIDGE_DRIVER",
            "title": "Bridge driver external components (Section 9.2 Table)",
            "text": "Section 9.2: Gate resistor R_GATE = 2..10 Ohm. Gate-to-source resistor R_GS = 100 kOhm. EMC filter capacitor C_EMCPx at SHx = 1 nF. Low-pass filter R_VDH = 1 kOhm, C_VDH = 1..3.3 nF. Source resistor R_SH = 2..10 Ohm."
        },
        {
            "chunk_id": "chunk_ch9_gate_ratio",
            "chapter_num": 9,
            "chapter_name": "Bridge driver (excluding charge pump)",
            "domain": "BRIDGE_DRIVER",
            "title": "Gate charge and capacitor ratio constraints",
            "text": "Gate-to-drain capacitor C_GD linearization: C_GD / C_GS <= 1 / 10 to avoid unintended switch-on during fast transients. Total gate charge Q_tot_max per MOSFET <= 100 nC for VQFN variants and 150 nC for TQFP variants."
        },
        {
            "chunk_id": "chunk_ch10_cp",
            "chapter_num": 10,
            "chapter_name": "Charge pump",
            "domain": "CHARGE_PUMP",
            "title": "Charge pump external capacitors design (Section 10.3)",
            "text": "Section 10.3: Flying capacitors C_CPS1 and C_CPS2 recommended value 220 nF (50V rating). Output bulk capacitor C_VCP recommended value 470 nF (50V rating). Filter resistor R_VSD = 2 Ohm, C_VSD = 1 uF."
        },
        {
            "chunk_id": "chunk_ch11_csa",
            "chapter_num": 11,
            "chapter_name": "Current sense amplifier",
            "domain": "CSA",
            "title": "CSA shunt resistor and filter network design",
            "text": "Section 11.4: Shunt resistor R_sh selected based on max current power dissipation. Filter network low-pass resistors R_LP = 1..15 Ohm. Anti-ringing filter cap C_LP = L_sh / (2 * R_LP * R_sh)."
        },
        {
            "chunk_id": "chunk_ch13_swd",
            "chapter_num": 13,
            "chapter_name": "SWD (serial wire debug) interface circuitry",
            "domain": "SWD",
            "title": "SWD connection and RESET pin capacitor",
            "text": "Section 13.2: Ceramic capacitor from RESET pin to GND = 1 nF to improve transient immunity. Blanking time 31 us configured in CNF_RST_TFB."
        },
        {
            "chunk_id": "chunk_ch14_table17",
            "chapter_num": 14,
            "chapter_name": "Unused pins",
            "domain": "UNUSED_PINS",
            "title": "Connecting unused pins (Table 17)",
            "text": "Table 17: CP1L, CP2H, CP2L, CP1H unused -> Open. VCP unused -> Open. GH1..3, GL1..3 unused -> Open. SH1..3, SL unused -> GND. MON unused -> GND or Open with internal PU/PD. GPIO unused -> GND or External PU/PD. VDH unused -> GND. VDDEXT unused -> Open. VSD unused -> GND or connect to VS for monitoring. LIN unused -> Open."
        }
    ]

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_path = os.path.join(base_dir, "data", "raw_doc", "chunks.json")
    with open(target_path, 'w', encoding='utf-8') as f:
        json.dump(chunks, f, indent=2)

    print(f"Successfully generated {len(chunks)} raw document chunks into {target_path}")


if __name__ == "__main__":
    generate_doc_chunks()
