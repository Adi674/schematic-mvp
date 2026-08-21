"""
MVP Generic Review Framework.

Actively executed checks (frozen at E1-E5 + R0 until extraction benchmarks pass):
  E1 — Scope & Readability
  E2 — Object Extraction Quality
  E3 — Geometry Validity
  E4 — Connectivity Confidence
  E5 — Evidence Completeness
  R0 — Section Identification Quality

Engineering checks R1-R6 are FROZEN until real-image extraction benchmarks pass.
"""

from typing import List
from src.schematic.schema import (
    SchematicFacts,
    CheckResultState,
    FindingItem,
    SchematicEvidence,
    FactState,
    ValidationStatus,
    SchematicObjectType,
    RefState
)


class ChecklistEngine:
    """Executes the frozen MVP extraction-quality checks."""

    def evaluate_framework(
        self,
        facts: SchematicFacts,
        selected_section: str
    ) -> List[FindingItem]:
        findings: List[FindingItem] = []

        findings.append(self._check_e1_scope(facts))
        findings.append(self._check_e2_object_quality(facts))
        findings.append(self._check_e3_geometry_validity(facts))
        findings.append(self._check_e4_connectivity_confidence(facts))
        findings.append(self._check_e5_evidence_completeness(facts))
        findings.append(self._check_r0_section_identification(selected_section))

        return findings

    # ------------------------------------------------------------------
    # E1 — Scope & Readability
    # ------------------------------------------------------------------
    def _check_e1_scope(self, facts: SchematicFacts) -> FindingItem:
        scope = facts.input_info.crop_scope
        width, height = facts.input_info.width, facts.input_info.height
        has_objects = len(facts.components) > 0 or len(facts.wires) > 0

        if not has_objects:
            status = CheckResultState.INSUFFICIENT_INPUT
            reason = "No objects detected. The crop may be blank, too blurry, or incorrectly formatted."
        elif scope == "partial":
            status = CheckResultState.NEEDS_REVIEW
            reason = (
                f"Crop is marked 'partial' ({width}×{height}px). "
                "Some circuit elements may be outside the supplied crop boundary."
            )
        else:
            status = CheckResultState.PASS
            reason = f"Crop scope is '{scope}' ({width}×{height}px). Objects detected."

        return FindingItem(
            check_id="E1",
            category="extraction",
            check_name="Scope & Readability",
            status=status,
            schematic_evidence=SchematicEvidence(
                components=[{"total_objects": len(facts.components)}]
            ),
            decision_reasoning=reason
        )

    # ------------------------------------------------------------------
    # E2 — Object Extraction Quality
    # ------------------------------------------------------------------
    def _check_e2_object_quality(self, facts: SchematicFacts) -> FindingItem:
        physical = [
            c for c in facts.components
            if c.object_type == SchematicObjectType.PHYSICAL_COMPONENT
        ]
        net_labels = [
            c for c in facts.components
            if c.object_type == SchematicObjectType.NET_LABEL
        ]
        functional_blocks = [
            c for c in facts.components
            if c.object_type == SchematicObjectType.FUNCTIONAL_BLOCK
        ]
        inferred_refs = [
            c for c in facts.components
            if c.ref_state == RefState.INFERRED
        ]
        unreadable_values = [
            c for c in facts.components
            if c.value_state in [FactState.UNKNOWN, FactState.UNREADABLE]
        ]

        status = CheckResultState.PASS
        notes = []
        if inferred_refs:
            status = CheckResultState.NEEDS_REVIEW
            notes.append(f"{len(inferred_refs)} reference(s) marked INFERRED (not engineering facts).")
        if len(unreadable_values) > len(physical) // 2 and physical:
            status = CheckResultState.NEEDS_REVIEW
            notes.append(f"{len(unreadable_values)} component value(s) unreadable.")

        reason = (
            f"Detected: {len(physical)} physical component(s), "
            f"{len(net_labels)} net label(s), "
            f"{len(functional_blocks)} functional block(s). "
            + (" ".join(notes) if notes else "All refs state OK.")
        )

        return FindingItem(
            check_id="E2",
            category="extraction",
            check_name="Object Extraction Quality",
            status=status,
            schematic_evidence=SchematicEvidence(
                components=[
                    {
                        "ref": str(c.ref or "?"),
                        "type": c.type,
                        "value": str(c.value or ""),
                        "ref_state": c.ref_state.value,
                        "value_state": c.value_state.value,
                        "object_type": c.object_type.value
                    }
                    for c in facts.components
                ]
            ),
            decision_reasoning=reason
        )

    # ------------------------------------------------------------------
    # E3 — Geometry Validity
    # ------------------------------------------------------------------
    def _check_e3_geometry_validity(self, facts: SchematicFacts) -> FindingItem:
        total = len(facts.components)
        invalid = [
            c for c in facts.components
            if c.validation_status == ValidationStatus.INVALID_GEOMETRY
        ]
        no_bbox = [
            c for c in facts.components
            if c.evidence is None or c.evidence.bbox is None
        ]
        geometry_applied = facts.geometry_stage_applied

        if not geometry_applied:
            status = CheckResultState.NEEDS_REVIEW
            reason = (
                "OpenCV geometry stage has not been applied. "
                "Bounding boxes are from LLM vision only (not geometrically validated). "
                f"{len(invalid)}/{total} objects have invalid geometry. "
                f"{len(no_bbox)}/{total} objects have no bounding box."
            )
        elif invalid:
            status = CheckResultState.NEEDS_REVIEW
            reason = f"{len(invalid)}/{total} objects have INVALID_GEOMETRY status."
        else:
            status = CheckResultState.PASS
            reason = f"All {total} object bounding boxes passed geometry validation."

        return FindingItem(
            check_id="E3",
            category="extraction",
            check_name="Geometry Validity",
            status=status,
            schematic_evidence=SchematicEvidence(
                components=[
                    {"ref": str(c.ref or "?"), "bbox_valid": c.validation_status != ValidationStatus.INVALID_GEOMETRY}
                    for c in facts.components
                ]
            ),
            decision_reasoning=reason
        )

    # ------------------------------------------------------------------
    # E4 — Connectivity Confidence
    # ------------------------------------------------------------------
    def _check_e4_connectivity_confidence(self, facts: SchematicFacts) -> FindingItem:
        has_nets = len(facts.nets) > 0
        has_wires = len(facts.wires) > 0
        geometry_applied = facts.geometry_stage_applied
        uncertainties = facts.uncertainties
        llm_inferred_nets = [n for n in facts.nets if n.source == "llm_inferred"]

        if not geometry_applied:
            status = CheckResultState.INSUFFICIENT_INPUT
            reason = (
                "Connectivity data is ABSENT. The OpenCV geometry stage has not run. "
                "Net memberships from LLM inference alone are NOT reliable engineering facts."
            )
        elif llm_inferred_nets:
            status = CheckResultState.NEEDS_REVIEW
            reason = (
                f"{len(llm_inferred_nets)} net(s) are LLM-inferred (not from geometry). "
                "Treat as approximate, not confirmed."
            )
        elif uncertainties:
            status = CheckResultState.NEEDS_REVIEW
            reason = (
                f"{len(uncertainties)} connectivity uncertainty(ies) remain unresolved: "
                + "; ".join(u.description for u in uncertainties[:3])
            )
        elif has_nets:
            status = CheckResultState.PASS
            reason = f"{len(facts.nets)} net(s) established from geometry. {len(uncertainties)} uncertainties."
        else:
            status = CheckResultState.INSUFFICIENT_INPUT
            reason = "No net connectivity data available for this crop."

        return FindingItem(
            check_id="E4",
            category="extraction",
            check_name="Connectivity Confidence",
            status=status,
            schematic_evidence=SchematicEvidence(
                net_connections=[{"net_id": n.net_id, "name": n.name, "source": n.source} for n in facts.nets],
                uncertainties=[u.description for u in uncertainties]
            ),
            decision_reasoning=reason
        )

    # ------------------------------------------------------------------
    # E5 — Evidence Completeness
    # ------------------------------------------------------------------
    def _check_e5_evidence_completeness(self, facts: SchematicFacts) -> FindingItem:
        total = len(facts.components)
        with_valid_bbox = sum(
            1 for c in facts.components
            if c.evidence and c.evidence.bbox_validated
        )
        coverage = (with_valid_bbox / total) if total else 0.0
        status = CheckResultState.PASS if coverage >= 0.50 else CheckResultState.NEEDS_REVIEW

        return FindingItem(
            check_id="E5",
            category="extraction",
            check_name="Evidence Completeness",
            status=status,
            schematic_evidence=SchematicEvidence(
                components=[
                    {
                        "ref": str(c.ref or "?"),
                        "has_valid_bbox": bool(c.evidence and c.evidence.bbox_validated),
                        "model_confidence": c.model_confidence
                    }
                    for c in facts.components
                ]
            ),
            decision_reasoning=(
                f"Valid bbox coverage: {int(coverage * 100)}% ({with_valid_bbox}/{total} objects). "
                + ("Sufficient for downstream geometry." if coverage >= 0.50 else
                   "Insufficient geometry evidence — visual debug overlay recommended.")
            )
        )

    # ------------------------------------------------------------------
    # R0 — Section Identification Quality
    # ------------------------------------------------------------------
    def _check_r0_section_identification(self, selected_section: str) -> FindingItem:
        return FindingItem(
            check_id="R0",
            category="extraction",
            check_name="Section Identification",
            status=CheckResultState.NEEDS_REVIEW,
            schematic_evidence=SchematicEvidence(),
            decision_reasoning=(
                f"Selected section: '{selected_section}'. "
                "Section confidence scores are NOT calibrated (no real-image benchmark yet). "
                "Engineering review checks (R1-R6) are FROZEN until extraction quality is benchmarked."
            )
        )
