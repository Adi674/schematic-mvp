"""
Explain Service — Scenario A ("Explain this schematic"), Workstream 4.

For each resolved component in an extracted SemanticSchematic:
  1. Resolve its net -> (net_name, function, domain) via net_resolution.py (WS2).
  2. Query the HDG knowledge base, domain-filtered, for table_row + section_prose
     evidence relevant to that net/function.
  3. Compose a grounded per-component explanation citing that evidence.
Then roll every per-component explanation into one coherent narrative.

Safety rules (mirrors reference_verifier.py):
  - Never invent a specification not present in retrieved evidence.
  - No evidence retrieved -> explanation says so explicitly (insufficient_evidence=True),
    never silently omitted and never backfilled from model knowledge.
  - Retriever/LLM failures degrade to an explicit "insufficient evidence" explanation
    for that component rather than raising and failing the whole crop.
"""

from __future__ import annotations

import json
from typing import Optional

from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.retrieval_schema import QueryResult
from src.llm import call_mistral_text, MistralAPIError, safe_print
from src.schematic.schema import ReferenceEvidence
from src.schematic.semantic_schema import SemanticSchematic
from src.schematic.net_resolution import (
    PinInfo,
    ResolvedNet,
    ComponentResolution,
    resolve_all_components,
)
from src.schematic.explain_schema import ComponentExplanation, ExplainCropResponse


EXPLAIN_SYSTEM_PROMPT = """You are a hardware design reference assistant explaining a schematic to an engineer.
Explain what the given component does using only the provided reference evidence.

Instructions:
1. State the component's function and, if the evidence supports it, its specification or design intent.
2. Do NOT invent, assume, or add technical values, limits, or design rules not present in the evidence.
3. You may paraphrase the evidence, but preserve its original technical scope.
4. If the evidence does not clearly cover this component, say plainly that the reference material
   does not provide enough information for it — do not guess.
5. Keep it to 2-4 sentences.

Return ONLY a JSON object:
{
  "explanation": "<2-4 sentence explanation>",
  "insufficient_evidence": true | false
}
"""

NARRATIVE_SYSTEM_PROMPT = """You are a hardware design reference assistant. You are given a set of
already-grounded, already-cited per-component explanations for one schematic crop. Combine them into
a single coherent narrative paragraph (or short set of paragraphs) describing what the crop as a whole
does, grouping related components (e.g. the same supply rail) together where natural.

Do NOT introduce any new facts, values, or components beyond what's in the provided explanations.
Do NOT drop the fact when a component's evidence was insufficient — say so briefly in the narrative
rather than omitting the component.
"""

_RETRIEVAL_UNIT_TYPES = ("table_row", "section_prose")


def _build_query(component_label: str, resolution: Optional[ResolvedNet]) -> str:
    if resolution is None:
        return f"TLE987x {component_label} function specification"
    parts = ["TLE987x"]
    if resolution.net_name:
        parts.append(resolution.net_name)
    if resolution.function:
        parts.append(resolution.function)
    parts.append(component_label)
    return " ".join(parts)


def _retrieve_evidence(
    retriever: HybridRetriever,
    query: str,
    domain: Optional[str],
    top_k_per_type: int = 2,
) -> list[QueryResult]:
    """Runs one retrieval pass per unit type (table_row, section_prose) since
    HybridRetriever.search only accepts a single unit_type_filter per call."""
    results: list[QueryResult] = []
    for unit_type in _RETRIEVAL_UNIT_TYPES:
        try:
            results.extend(
                retriever.search(
                    query=query,
                    top_k=top_k_per_type,
                    domain_filter=domain,
                    unit_type_filter=unit_type,
                )
            )
        except Exception as e:
            safe_print(f"[EXPLAIN] Retrieval error for unit_type={unit_type}: {e}")
    return results


def _compose_explanation(
    component_label: str,
    resolution: Optional[ResolvedNet],
    results: list[QueryResult],
) -> ComponentExplanation:
    net_name = resolution.net_name if resolution else None
    function = resolution.function if resolution else None
    domain = resolution.domain if resolution else None
    resolution_kind = resolution.resolution if resolution else "unresolved"

    if not results:
        return ComponentExplanation(
            component_label=component_label,
            net_name=net_name,
            function=function,
            domain=domain,
            resolution=resolution_kind,
            explanation=(
                f"No reference evidence was retrieved for {component_label}. "
                "The Hardware Design Guideline does not provide enough information "
                "to explain this component's function."
            ),
            insufficient_evidence=True,
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
                source_text=r.unit.text_content[:300],
            )
        )
    ref_text = "\n\n".join(ref_blocks)

    user_prompt = (
        f"Component: {component_label}\n"
        f"Resolved net: {net_name or 'unresolved'}\n"
        f"Net function: {function or 'unknown'}\n"
        f"Domain: {domain or 'unknown'}\n\n"
        f"Retrieved Reference Evidence:\n{ref_text}"
    )

    explanation_text = (
        f"Reference evidence was retrieved for {component_label} but composition "
        "could not be completed. Manual review required."
    )
    insufficient = False

    try:
        llm_raw = call_mistral_text(
            system_prompt=EXPLAIN_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        if llm_raw and "{" in llm_raw and "}" in llm_raw:
            json_str = llm_raw[llm_raw.find("{"): llm_raw.rfind("}") + 1]
            parsed = json.loads(json_str)
            explanation_text = parsed.get("explanation", explanation_text)
            insufficient = bool(parsed.get("insufficient_evidence", False))
        elif llm_raw:
            explanation_text = llm_raw.strip()
    except MistralAPIError as e:
        safe_print(f"[EXPLAIN] LLM API error for {component_label}: {e}")
        insufficient = True
        explanation_text = (
            f"Reference evidence was retrieved for {component_label}, but the "
            "explanation could not be generated due to an LLM error. Manual review required."
        )
    except Exception as e:
        safe_print(f"[EXPLAIN] LLM parse error for {component_label}: {e}")
        insufficient = True
        explanation_text = (
            f"Reference evidence was retrieved for {component_label}, but the "
            "response could not be parsed. Manual review required."
        )

    return ComponentExplanation(
        component_label=component_label,
        net_name=net_name,
        function=function,
        domain=domain,
        resolution=resolution_kind,
        explanation=explanation_text,
        reference_evidence=reference_evidence,
        insufficient_evidence=insufficient,
    )


def _compose_narrative(explanations: list[ComponentExplanation]) -> str:
    if not explanations:
        return "No components were resolved for this crop."

    summary_blocks = []
    for exp in explanations:
        summary_blocks.append(
            f"- {exp.component_label} (net: {exp.net_name or 'unresolved'}): {exp.explanation}"
        )
    user_prompt = "Per-component explanations:\n" + "\n".join(summary_blocks)

    try:
        narrative = call_mistral_text(
            system_prompt=NARRATIVE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        return narrative.strip() if narrative else user_prompt
    except MistralAPIError as e:
        safe_print(f"[EXPLAIN] Narrative rollup LLM error: {e}")
        # Degrade to the raw per-component list rather than failing the crop.
        return user_prompt
    except Exception as e:
        safe_print(f"[EXPLAIN] Narrative rollup error: {e}")
        return user_prompt


def explain_schematic(
    semantic: SemanticSchematic,
    pin_index: dict[str, PinInfo],
    retriever: Optional[HybridRetriever] = None,
    review_id: str = "",
) -> ExplainCropResponse:
    """Top-level WS4 entry point: extraction (already done) -> net resolution
    -> per-component retrieval + composition -> narrative rollup."""
    retriever = retriever or HybridRetriever()

    resolutions: dict[str, ComponentResolution] = resolve_all_components(semantic, pin_index)

    explanations: list[ComponentExplanation] = []
    for component in semantic.components:
        if not component.label:
            continue
        resolution = resolutions.get(component.label)
        primary = resolution.primary if resolution else None

        query = _build_query(component.label, primary)
        domain = primary.domain if primary else None
        results = _retrieve_evidence(retriever, query, domain)

        explanations.append(_compose_explanation(component.label, primary, results))

    narrative = _compose_narrative(explanations)

    return ExplainCropResponse(
        review_id=review_id,
        device_context=semantic.device_context,
        component_explanations=explanations,
        narrative=narrative,
    )