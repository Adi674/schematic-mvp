"""
Missing Check Service — Scenario B ("What's missing"), Workstream 5.

Diff scope, deliberately narrow for a crop-based MVP:
  - Only nets the CUSTOMER'S CROP actually touches are checked. A crop of the
    VDDP/VDDC/VDDEXT decoupling network is not diffed against the full-chip
    reference (that would flag the bridge driver, Hall sensors, etc. as
    "missing" from a crop that was never meant to show them) — it's diffed
    only against what the reference says SHOULD be on the nets the crop
    itself contains.
  - Presence-only: checks whether a component of the expected TYPE is present
    on that net, not whether it's wired in the right position (FR-017,
    explicitly out of scope).
  - Customer supporting-document scoping (skip nets the customer's doc says
    aren't used) is read per-request, not wired into the shared KB — plan
    calls this out as a separate follow-up; not implemented here yet.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from src.retrieval.hybrid_retriever import HybridRetriever
from src.llm import call_mistral_text, MistralAPIError, safe_print
from src.schematic.schema import ReferenceEvidence
from src.schematic.semantic_schema import SemanticSchematic
from src.schematic.missing_schema import MissingComponentFinding, MissingCropResponse
from src.schematic.net_resolution import NON_DISTINGUISHING_NETS


MISSING_SYSTEM_PROMPT = """You are a hardware design reference auditor explaining why a specific
component is required on a net, using only the provided reference evidence.

Instructions:
1. State why the reference material requires this type of component on this net.
2. Do NOT invent values, limits, or requirements not present in the evidence.
3. If the evidence does not clearly establish a requirement, say plainly that the reference
   material does not provide enough information — do not guess.
4. Keep it to 1-3 sentences.

Return ONLY a JSON object:
{
  "reasoning": "<1-3 sentence explanation of why this component is required>",
  "insufficient_evidence": true | false
}
"""

_REFERENCE_DIR = Path("data/reference_schematics")

# Maps device_context substrings (from extraction) to reference schematic filenames.
# Extend as more device variants get bootstrapped ground truth.
_DEVICE_FILE_MAP = {
    "tle987x-2qx": "tle987x_2qx.json",
    "tle987x": "tle987x_bootstrap_groundtruth.json",
}


def _select_reference_file(device_context: Optional[str]) -> Optional[Path]:
    ctx = (device_context or "").lower()
    for key, filename in _DEVICE_FILE_MAP.items():
        if key in ctx:
            path = _REFERENCE_DIR / filename
            if path.exists():
                return path
    # Fall back to the base TLE987x reference if nothing matched — better to
    # diff against something than silently skip WS5 entirely.
    fallback = _REFERENCE_DIR / "tle987x_bootstrap_groundtruth.json"
    return fallback if fallback.exists() else None


def load_reference_schematic(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _normalize_reference_data(reference_data: dict) -> dict[str, list[dict]]:
    components = reference_data.get("components", [])

    if reference_data.get("nets"):
        comp_by_ref = {c.get("ref"): c for c in components if c.get("ref")}
        expected_by_net: dict[str, list[dict]] = {}
        for net in reference_data["nets"]:
            net_name = (net.get("name") or "").upper()
            if not net_name:
                continue
            for ref in net.get("connections", []):
                comp = comp_by_ref.get(ref)
                if comp is None:
                    continue
                expected_by_net.setdefault(net_name, []).append({
                    "ref": comp.get("ref"),
                    "type": comp.get("type"),
                    "function": comp.get("function"),
                    "section": comp.get("section"),
                })
        return expected_by_net

    expected_by_net = {}
    for comp in components:
        ref = comp.get("label")
        if not ref:
            continue
        for node_name in comp.get("nodes", []):
            if not node_name:
                continue
            expected_by_net.setdefault(node_name.upper(), []).append({
                "ref": ref,
                "type": comp.get("type"),
                "function": comp.get("function"),
                "section": None,
            })
    return expected_by_net


def _extracted_types_by_net(semantic: SemanticSchematic) -> dict[str, set[str]]:
    """Net name (uppercased) -> set of component `type` strings touching it,
    derived from the extraction's own connections."""
    node_names = {n.name.upper() for n in semantic.nodes}
    comp_by_label = {c.label: c for c in semantic.components if c.label}

    result: dict[str, set[str]] = {}
    for conn in semantic.connections:
        src, tgt = conn.source, conn.target
        for net_side, comp_side in ((src, tgt), (tgt, src)):
            if net_side.upper() in node_names and comp_side in comp_by_label:
                comp = comp_by_label[comp_side]
                if comp.type:
                    result.setdefault(net_side.upper(), set()).add(comp.type.lower())
    return result


def _retrieve_and_compose_reasoning(
    retriever: HybridRetriever,
    net_name: str,
    expected_type: str,
    function: Optional[str],
    domain: Optional[str],
) -> tuple[str, list[ReferenceEvidence], bool]:
    query = f"TLE987x {net_name} {expected_type} {function or ''}".strip()
    try:
        results = retriever.search(
            query=query, top_k=3, domain_filter=domain, unit_type_filter="table_row"
        )
        if not results:
            results = retriever.search(query=query, top_k=3, domain_filter=domain)
    except Exception as e:
        safe_print(f"[MISSING_CHECK] Retrieval error for {net_name}/{expected_type}: {e}")
        results = []

    if not results:
        return (
            f"No reference evidence was retrieved establishing a requirement for "
            f"a {expected_type} on {net_name}.",
            [],
            True,
        )

    ref_blocks = []
    reference_evidence: list[ReferenceEvidence] = []
    for idx, r in enumerate(results, 1):
        ref_blocks.append(
            f"[Source {idx} — Page {r.unit.page_start}, Sec {r.unit.section_number}]\n"
            f"{r.unit.text_content.strip()}"
        )
        reference_evidence.append(
            ReferenceEvidence(
                document="TLE987x/6x Hardware Design Guideline",
                page=r.unit.page_start,
                section=r.unit.section_number,
                unit_id=r.unit_id,
                source_text=r.unit.text_content[:600],
            )
        )
    ref_text = "\n\n".join(ref_blocks)

    user_prompt = (
        f"Net: {net_name}\nExpected component type: {expected_type}\n"
        f"Function: {function or 'unknown'}\n\nRetrieved Reference Evidence:\n{ref_text}"
    )

    reasoning = (
        f"Reference evidence was retrieved for {net_name}/{expected_type} but composition "
        "could not be completed. Manual review required."
    )
    insufficient = False
    try:
        llm_raw = call_mistral_text(system_prompt=MISSING_SYSTEM_PROMPT, user_prompt=user_prompt)
        if llm_raw and "{" in llm_raw and "}" in llm_raw:
            parsed = json.loads(llm_raw[llm_raw.find("{"): llm_raw.rfind("}") + 1])
            reasoning = parsed.get("reasoning", reasoning)
            insufficient = bool(parsed.get("insufficient_evidence", False))
        elif llm_raw:
            reasoning = llm_raw.strip()
    except MistralAPIError as e:
        safe_print(f"[MISSING_CHECK] LLM API error for {net_name}/{expected_type}: {e}")
        insufficient = True
        reasoning = (
            f"Reference evidence was retrieved for {net_name}/{expected_type}, but the "
            "explanation could not be generated due to an LLM error. Manual review required."
        )
    except Exception as e:
        safe_print(f"[MISSING_CHECK] LLM parse error: {e}")
        insufficient = True

    return reasoning, reference_evidence, insufficient


def check_missing_components(
    semantic: SemanticSchematic,
    retriever: Optional[HybridRetriever] = None,
    review_id: str = "",
    reference_data: Optional[dict] = None,
    reference_device: Optional[str] = None,
) -> MissingCropResponse:
    retriever = retriever or HybridRetriever()
    review_id = review_id or str(uuid.uuid4())

    if reference_data is None:
        ref_path = _select_reference_file(semantic.device_context)
        if ref_path is None:
            return MissingCropResponse(
                review_id=review_id,
                device_context=semantic.device_context,
                summary="No reference schematic available for this device — cannot run missing-component check.",
            )
        reference_data = load_reference_schematic(ref_path)
        reference_device = ref_path.name

        # The reference schema (see scripts/build_reference_schematics.py) has no
        # top-level "nets" list — each component instead carries the net names it
        # touches in its own "nodes" field, and its refdes lives under "label"
        # (not "ref"). Build the net -> expected-components index from that.
        expected_by_net: dict[str, list[dict]] = {}
        for comp in reference_data.get("components", []):
            for node_name in comp.get("nodes", []):
                if not node_name:
                    continue
                expected_by_net.setdefault(node_name.upper(), []).append(comp)

        extracted_node_names = {n.name.upper() for n in semantic.nodes}
        extracted_types_by_net = _extracted_types_by_net(semantic)

        nets_checked: list[str] = []
        findings: list[MissingComponentFinding] = []

        for net_name_upper, expected_components in expected_by_net.items():
            if net_name_upper not in extracted_node_names:
                continue  # net not present in this crop — out of scope for this diff
            net_name = net_name_upper
            nets_checked.append(net_name)

            present_types = extracted_types_by_net.get(net_name_upper, set())

            for exp in expected_components:
                exp_ref = exp.get("label")
                if not exp_ref:
                    continue
                exp_type = (exp.get("type") or "").lower()

            if exp_type in present_types:
                findings.append(
                    MissingComponentFinding(
                        expected_ref=exp_ref,
                        expected_type=exp.get("type", ""),
                        net_name=net_name,
                        section=exp.get("section"),
                        function=exp.get("function"),
                        status="PRESENT",
                        reasoning=f"A {exp_type} is present on {net_name}, matching the reference.",
                    )
                )
                continue

            reasoning, ref_evidence, insufficient = _retrieve_and_compose_reasoning(
                retriever, net_name, exp.get("type", ""), exp.get("function"), domain=None
            )
            findings.append(
                MissingComponentFinding(
                    expected_ref=exp_ref,
                    expected_type=exp.get("type", ""),
                    net_name=net_name,
                    section=exp.get("section"),
                    function=exp.get("function"),
                    status="MISSING",
                    reasoning=reasoning,
                    reference_evidence=ref_evidence,
                    insufficient_evidence=insufficient,
                )
            )

    missing_count = sum(1 for f in findings if f.status == "MISSING")
    total = len(findings)
    summary = (
        f"{missing_count} of {total} expected components missing on the "
        f"{len(nets_checked)} checked net(s): {', '.join(nets_checked) or 'none'}."
        if total
        else "No reference nets overlapped with this crop — nothing to check."
    )

    return MissingCropResponse(
        review_id=review_id,
        device_context=semantic.device_context,
        reference_device=reference_device,
        nets_checked=nets_checked,
        findings=findings,
        summary=summary,
    )