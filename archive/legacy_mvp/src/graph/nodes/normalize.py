"""
Unit parser and normalizer for hardware components.
Parses value strings (e.g. "470 nF + 1 µF (1.47 µF)", "4.7uF", "10kΩ", "2.2 µF type: X7R")
into canonical SI floats (Farads, Ohms, Volts, Hertz).
"""

import re
from typing import Optional, Tuple, Dict, Any

# SI Multipliers
PREFIX_MULTIPLIERS = {
    'p': 1e-12,
    'n': 1e-9,
    'u': 1e-6,
    'µ': 1e-6,
    'm': 1e-3,
    'k': 1e3,
    'M': 1e6,
    'G': 1e9,
}

# Unit types
UNIT_TYPES = {
    'F': 'capacitance',
    'Ω': 'resistance',
    'Ω': 'resistance',
    'Ohm': 'resistance',
    'ohm': 'resistance',
    'V': 'voltage',
    'Hz': 'frequency',
    'A': 'current',
}


def parse_single_si_value(val_str: str) -> Optional[Tuple[float, str]]:
    """
    Parses a single engineering value string like '470nF', '1.47 µF', '3.9 kΩ', '220 Ω'.
    Returns (float_val, unit_type) or None if parsing fails.
    """
    if not val_str:
        return None

    val_str = val_str.strip()

    # Pattern to match number (float/int) + optional prefix + unit
    # Matches e.g. 470, 1.47, 0.47 followed by p/n/u/µ/m/k/M/G followed by F/Ω/Ω/Ohm/V/Hz/A
    pattern = r'([0-9]+(?:\.[0-9]+)?)\s*([pnuµmkMG])?\s*([FΩΩVHA]|Hz|Ohm|ohm)?'
    match = re.search(pattern, val_str)
    if not match:
        return None

    number_str, prefix, unit_symbol = match.groups()
    if not number_str:
        return None

    number = float(number_str)
    multiplier = PREFIX_MULTIPLIERS.get(prefix, 1.0) if prefix else 1.0
    val_si = number * multiplier

    unit_type = 'unknown'
    if unit_symbol:
        unit_type = UNIT_TYPES.get(unit_symbol, 'unknown')

    return val_si, unit_type


def parse_value_expression(val_str: str) -> Optional[float]:
    """
    Parses complex expressions like:
    - '470 nF + 1 µF (1.47 µF)' -> returns 1.47e-6
    - '470 nF + 100 nF' -> returns 5.7e-7
    - '4.7uF' -> returns 4.7e-6
    - 'Min. value 100 nF type: X7R' -> returns 1e-7
    """
    if not val_str:
        return None

    # Check if there is an explicit value inside parentheses like (1.47 µF) or (430 nF) or (2 µF)
    paren_match = re.search(r'\(([^)]+)\)', val_str)
    if paren_match:
        inner_str = paren_match.group(1)
        res = parse_single_si_value(inner_str)
        if res:
            return res[0]

    # Check for addition expression like "470 nF + 1 µF" or "100 nF + 330 nF"
    if '+' in val_str:
        parts = val_str.split('+')
        total = 0.0
        parsed_any = False
        for part in parts:
            res = parse_single_si_value(part)
            if res:
                total += res[0]
                parsed_any = True
        if parsed_any:
            return total

    # Fallback to single value extraction
    res = parse_single_si_value(val_str)
    if res:
        return res[0]

    return None


def parse_value_range(val_str: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Parses range strings like:
    - '1.47uF - 4.4uF' -> (1.47e-6, 4.4e-6)
    - '2 ... 10 Ω' -> (2.0, 10.0)
    - 'Min. value: 100 nF' -> (1.0e-7, None)
    """
    if not val_str:
        return None, None

    # Check for range with hyphen or ellipsis "1.47uF - 4.4uF" or "2 ... 10"
    range_match = re.search(r'([0-9.]+\s*[pnuµmkMG]?[FΩΩVHA]?)\s*(?:-|---|...|\bto\b)\s*([0-9.]+\s*[pnuµmkMG]?[FΩΩVHA]?)', val_str)
    if range_match:
        low_str, high_str = range_match.groups()
        low_val = parse_value_expression(low_str)
        high_val = parse_value_expression(high_str)
        return low_val, high_val

    # Single value parsed as min value
    val = parse_value_expression(val_str)
    return val, None


def normalize_component_record(raw_component: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes a raw component dictionary into canonical SI floats.
    Input format: {"designator": "C15", "value": "1.2uF", "pin": "VDDP", "confidence": "high"}
    Output format: {"designator": "C15", "value_raw": "1.2uF", "value_SI": 1.2e-6, "unit": "F", ...}
    """
    val = raw_component.get("value")
    raw_val = str(val).strip() if val is not None else ""
    si_val = parse_value_expression(raw_val) if raw_val else None

    unit = "F"
    if raw_val:
        if "kΩ" in raw_val or "kOhm" in raw_val or "Ω" in raw_val or "Ω" in raw_val or "ohm" in raw_val.lower():
            unit = "Ohm"
        elif "V" in raw_val and "mV" not in raw_val:
            unit = "V"
        elif "Hz" in raw_val:
            unit = "Hz"

    return {
        "designator": raw_component.get("designator", ""),
        "type": raw_component.get("type", "capacitor"),
        "value_raw": val,
        "value_SI": si_val,
        "unit": unit,
        "pin": raw_component.get("pin", ""),
        "net": raw_component.get("net", ""),
        "confidence": raw_component.get("confidence", 1.0)
    }

