"""
Router Node.
Determines active pipeline routes: 'exact_lookup', 'rag', and/or 'extraction'.
Returns matched_symbol and inferred_domain for downstream nodes.
"""

import sqlite3
import os
from typing import List, Dict, Any
from src.graph.state import PipelineState

# Complete symbol and pin list derived from rules_source.json
# Maps symbol -> domain for domain-filtered RAG retrieval
SYMBOL_DOMAIN_MAP = {
    # PGU domain
    "C_VS1": "PGU", "C_VS2": "PGU", "C_VDDP": "PGU", "C_VDDC": "PGU",
    "C_VDDEXT": "PGU", "C_VAREF": "PGU", "I_PRE": "PGU",
    # CLOCK domain
    "C_XTAL1": "CLOCK", "C_XTAL2": "CLOCK", "R_XTAL2": "CLOCK",
    # GPIO domain
    "R_PU": "GPIO", "R_IO": "GPIO",
    # LIN domain
    "C_LIN": "LIN",
    # MON domain
    "R_MON": "MON", "C_MON": "MON",
    # ADC domain
    "R_ADC1IN": "ADC", "C_ADC1IN": "ADC",
    "R_SINCOS": "ADC", "C_SINCOS": "ADC", "C_HF": "ADC",
    # BRIDGE_DRIVER domain
    "R_GATE": "BRIDGE_DRIVER", "R_GS": "BRIDGE_DRIVER",
    "C_GD": "BRIDGE_DRIVER", "C_GS": "BRIDGE_DRIVER",
    "R_VDH": "BRIDGE_DRIVER", "C_VDH": "BRIDGE_DRIVER",
    "C_EMCPx": "BRIDGE_DRIVER", "C_EMCP": "BRIDGE_DRIVER",
    "R_SH": "BRIDGE_DRIVER",
    # CHARGE_PUMP domain
    "C_CPS1": "CHARGE_PUMP", "C_CPS2": "CHARGE_PUMP", "C_VCP": "CHARGE_PUMP",
    # CSA domain
    "R_LP": "CSA",
    # SWD domain
    "C_RESET": "SWD",
    # UNUSED_PINS domain
    "CP1L_CP2H_CP2L_CP1H": "UNUSED_PINS", "SH1_SH2_SH3_SL": "UNUSED_PINS",
    "MON_UNUSED": "UNUSED_PINS", "GPIO_UNUSED": "UNUSED_PINS",
    "VDH_UNUSED": "UNUSED_PINS",
}

# Pin names that map to domains (for pin-level matching)
PIN_DOMAIN_MAP = {
    "VS": "PGU", "VDDP": "PGU", "VDDC": "PGU", "VDDEXT": "PGU",
    "VAREF": "PGU", "VPRE": "PGU",
    "XTAL1": "CLOCK", "XTAL2": "CLOCK",
    "GPIO": "GPIO",
    "LIN": "LIN",
    "MON": "MON",
    "ADC1": "ADC", "SDADC": "ADC",
    "GHX": "BRIDGE_DRIVER", "GLX": "BRIDGE_DRIVER",
    "VDH": "BRIDGE_DRIVER", "SHX": "BRIDGE_DRIVER",
    "CP1H": "CHARGE_PUMP", "CP1L": "CHARGE_PUMP",
    "CP2H": "CHARGE_PUMP", "CP2L": "CHARGE_PUMP", "VCP": "CHARGE_PUMP",
    "OP1": "CSA", "OP2": "CSA",
    "RESET": "SWD", "SWD": "SWD", "TMS": "SWD",
}


def router_node(state: PipelineState) -> Dict[str, Any]:
    question = state.get("question", "")
    question_upper = question.upper()
    image = state.get("image")

    routes = []
    matched_symbol = None
    inferred_domain = None

    # 1. Image presence triggers extraction
    if image is not None:
        routes.append("extraction")

    # 2. Check for explicit symbol mention (e.g. C_VDDP, R_GATE)
    symbols_by_length = sorted(SYMBOL_DOMAIN_MAP.keys(), key=len, reverse=True)
    for sym in symbols_by_length:
        if sym.upper() in question_upper:
            matched_symbol = sym
            inferred_domain = SYMBOL_DOMAIN_MAP[sym]
            if "exact_lookup" not in routes:
                routes.append("exact_lookup")
            break

    # 3. If no symbol matched, check for explicit pin mentions using word boundaries (e.g. \bVDDP\b, \bVS\b)
    if not matched_symbol:
        pins_by_length = sorted(PIN_DOMAIN_MAP.keys(), key=len, reverse=True)
        for pin in pins_by_length:
            import re
            if re.search(r'\b' + re.escape(pin) + r'\b', question_upper):
                matched_symbol = pin
                inferred_domain = PIN_DOMAIN_MAP[pin]
                if "exact_lookup" not in routes:
                    routes.append("exact_lookup")
                break

    # 4. Check if question is focused on the image/schematic diagram
    IMAGE_INTENT_KEYWORDS = ["DIAGRAM", "SCHEMATIC", "IMAGE", "PICTURE", "CIRCUIT",
                             "PRESENT IN", "SHOWN IN", "VISIBLE", "THIS PORTION",
                             "THIS SNIPPET", "UPLOADED", "COMPONENTS AND PINS", "PINS WHICH"]
    is_image_focused = image is not None or any(k in question_upper for k in IMAGE_INTENT_KEYWORDS)

    # 5. Check if question requires explanatory RAG retrieval
    needs_explanation = any(w in question_upper for w in ["WHY", "HOW", "EXPLAIN", "PURPOSE", "FUNCTION", "REASON", "RECOMMENDATION"])

    # Package specific queries
    is_package_q = any(w in question_upper for w in ["PACKAGE", "VQFN", "TQFP", "TOTAL PINS", "PIN COUNT", "HOW MANY PINS"])

    if is_image_focused:
        # For image queries: only add RAG if user specifically asked for conceptual explanation
        if needs_explanation and "rag" not in routes:
            routes.append("rag")
    else:
        # Text-only queries
        if is_package_q or not matched_symbol or needs_explanation:
            if "rag" not in routes:
                routes.append("rag")

    return {
        "routes": routes,
        "matched_symbol": matched_symbol,
        "inferred_domain": inferred_domain,
    }

