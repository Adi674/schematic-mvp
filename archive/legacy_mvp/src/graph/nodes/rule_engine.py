"""
Deterministic Rule Engine Node.
Queries rules.db and evaluates normalized schematic components against ground-truth constraints.
"""

import os
import json
import sqlite3
from typing import List, Dict, Any


def get_db_connection():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    db_path = os.path.join(base_dir, "data", "rules", "rules.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def evaluate_single_component(comp: Dict[str, Any], rule_row: sqlite3.Row) -> Dict[str, Any]:
    """
    Evaluates a single component against a static range rule.
    Returns CheckResult dictionary.
    """
    symbol = comp.get("symbol", comp.get("designator", ""))
    val_si = comp.get("value_SI")
    confidence = comp.get("confidence", 1.0)
    pin = comp.get("pin", rule_row["pin"])

    min_val = rule_row["min_value_SI"]
    max_val = rule_row["max_value_SI"]
    req_dielectric = rule_row["dielectric_required"]
    min_volt = rule_row["voltage_rating_min_V"]

    # Low confidence handling
    if confidence < 0.7:
        return {
            "component": symbol,
            "pin": pin,
            "status": "FAIL_LOW_CONFIDENCE",
            "expected": f"Min: {min_val}, Max: {max_val}",
            "actual": comp.get("value_raw", "unknown"),
            "confidence": "low",
            "reason": f"Extraction confidence ({confidence:.2f}) is below threshold 0.70",
            "source": {
                "table": rule_row["source_table"],
                "page": rule_row["source_page"],
                "chunk_id": rule_row["source_chunk_id"]
            }
        }

    if val_si is None:
        return {
            "component": symbol,
            "pin": pin,
            "status": "NEEDS_INPUT",
            "expected": f"Min: {min_val}, Max: {max_val}" + (f", {req_dielectric}" if req_dielectric else ""),
            "actual": comp.get("value_raw") or "Not labeled",
            "confidence": "medium",
            "reason": "Numerical component value is not labeled in the schematic diagram",
            "source": {
                "table": rule_row["source_table"],
                "page": rule_row["source_page"],
                "chunk_id": rule_row["source_chunk_id"]
            }
        }

    status = "PASS"
    reason = "Value is within specified tolerance limits"

    if min_val is not None and val_si < min_val:
        deficit_pct = (min_val - val_si) / min_val * 100
        if deficit_pct <= 20.0:
            status = "MARGINAL_LOW"
            reason = f"Value is ~{deficit_pct:.1f}% below specified minimum ({min_val})"
        else:
            status = "FAIL"
            reason = f"Value is significantly below specified minimum ({min_val})"

    elif max_val is not None and val_si > max_val:
        excess_pct = (val_si - max_val) / max_val * 100
        if excess_pct <= 20.0:
            status = "MARGINAL_HIGH"
            reason = f"Value is ~{excess_pct:.1f}% above specified maximum ({max_val})"
        else:
            status = "FAIL"
            reason = f"Value is significantly above specified maximum ({max_val})"

    return {
        "component": symbol,
        "pin": pin,
        "status": status,
        "expected": f"Min: {min_val if min_val else 'N/A'}, Max: {max_val if max_val else 'N/A'}" + (f", {req_dielectric}" if req_dielectric else ""),
        "actual": comp.get("value_raw", str(val_si)),
        "confidence": "high",
        "reason": reason,
        "source": {
            "table": rule_row["source_table"],
            "page": rule_row["source_page"],
            "chunk_id": rule_row["source_chunk_id"]
        }
    }


def run_rule_engine(normalized_components: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Executes rule engine checks for a list of normalized components.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    results = []

    for comp in normalized_components:
        symbol = comp.get("symbol", "")
        pin = comp.get("pin", "")

        # Try matching by symbol or pin
        cursor.execute("SELECT * FROM rules WHERE symbol = ? OR pin = ?", (symbol, pin))
        rule_row = cursor.fetchone()

        if not rule_row:
            results.append({
                "component": symbol or pin or "Unknown",
                "pin": pin,
                "status": "NO_RULE_FOUND",
                "expected": "N/A",
                "actual": comp.get("value_raw", "unknown"),
                "confidence": "high",
                "reason": f"No ground-truth rule found in rules.db for symbol '{symbol}' / pin '{pin}'",
                "source": None
            })
        else:
            res = evaluate_single_component(comp, rule_row)
            results.append(res)

    conn.close()
    return results
