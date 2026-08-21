"""
Sanity Check Node.
Verifies natural language answer consistency against structured rule verdicts.
Catches contradictions (e.g. text saying "looks good" next to a FAIL status).
"""

from typing import Dict, Any, List
from src.graph.state import PipelineState


def sanity_check_node(state: PipelineState) -> Dict[str, Any]:
    checklist_report = state.get("checklist_report", [])
    final_answer = state.get("final_answer", "")

    flags: List[str] = []

    has_fail = any(r.get("status") in ["FAIL", "MARGINAL_LOW", "MARGINAL_HIGH"] for r in checklist_report)

    if has_fail and ("everything looks good" in final_answer.lower() or "no violations" in final_answer.lower()):
        flags.append("CONTRADICTION_DETECTED: Answer text claims no violations despite FAIL/MARGINAL verdicts.")

    return {
        "sanity_flags": flags
    }
