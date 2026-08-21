"""
Pinout Map Utility.
Resolves net names and pin numbers to canonical TLE987x pin names and domains.
"""

import os
import json
from typing import Optional, Dict, Any


def load_pinout_map() -> Dict[str, Any]:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pinout_path = os.path.join(base_dir, "data", "pinout_map", "tle987x_pinout.json")
    if not os.path.exists(pinout_path):
        raise FileNotFoundError(f"Pinout map file not found at: {pinout_path}")

    with open(pinout_path, 'r', encoding='utf-8') as f:
        return json.load(f)


PINOUT_DATA = load_pinout_map()


def resolve_net_to_canonical_pin(net_name: str) -> Optional[Dict[str, Any]]:
    """
    Fuzzy-resolves net names (e.g. "VDDP_RAIL", "PIN40_VDDP", "VDDP", "VS_IN")
    to canonical pin dictionary {"pin_number": 40, "name": "VDDP", "domain": "PGU"}.
    """
    if not net_name:
        return None

    net_clean = net_name.upper().strip()

    # Exact pin name match
    for pin_num, pin_info in PINOUT_DATA["pins"].items():
        pin_name = pin_info["name"].upper()
        if pin_name == net_clean or pin_name in net_clean:
            return pin_info

    return None
