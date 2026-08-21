"""
Reference Verifier Module.

Queries HybridRetriever + Mistral text LLM to compare extracted schematic
facts against hardware design guideline requirements.

Safety rules:
  - NEVER default to PASS.
  - Retriever failure → NEEDS_REVIEW.
  - LLM failure → NEEDS_REVIEW.
  - No reference evidence retrieved → INSUFFICIENT_INPUT.
  - Queries are check-specific, not generic concatenation.
"""

import json
from typing import List, Optional
from src.retrieval.hybrid_retriever import HybridRetriever
from src.llm import call_mistral_text, MistralAPIError, safe_print
from src.schematic.schema import (
    SchematicFacts,
    FindingItem,
    CheckResultState,
    SchematicEvidence,
    ReferenceEvidence,
    SchematicObjectType,
    FactState
)


R5_COMPARISON_SYSTEM_PROMPT = """You are an expert hardware design review auditor.
Compare observed electrical facts from a schematic crop against retrieved reference evidence from the official TLE987x/6x Hardware Design Guideline.

Instructions:
1. Compare observed facts (components, values, connections) against the reference evidence.
2. Decide: "PASS", "FAIL", "WARNING", "INSUFFICIENT_INPUT", or "NEEDS_REVIEW".
3. Do NOT invent engineering limits. All limits must come from the reference evidence.
4. If reference evidence does not cover the observed fact, return "INSUFFICIENT_INPUT".
5. If retrieval evidence is ambiguous or partial, return "NEEDS_REVIEW".
6. Never return "PASS" unless the reference evidence explicitly confirms the observed facts are correct.

Return ONLY a JSON object:
{
  "status": "PASS" | "FAIL" | "WARNING" | "INSUFFICIENT_INPUT" | "NEEDS_REVIEW",
  "reason": "<2-3 sentence engineering evaluation citing section/page>"
}
"""


class ReferenceVerifier:
    """Queries the knowledge base and compares schematic facts to reference requirements."""

    def __init__(self, retriever: Optional[HybridRetriever] = None):
        self.retriever = retriever or HybridRetriever()

    def verify_section_requirements(
        self,
        facts: SchematicFacts,
        selected_section: str
    ) -> FindingItem:
        """
        Runs the R5 reference comparison check.
        Default status is NEEDS_REVIEW — never PASS — until evidence confirms it.
        """
        # Build check-specific query (not generic concatenation)
        physical_comps = [
            c for c in facts.components
            if c.object_type == SchematicObjectType.PHYSICAL_COMPONENT
            and c.value_state == FactState.VALIDATED
        ]
        net_labels = [
            c.value for c in facts.components
            if c.object_type == SchematicObjectType.NET_LABEL and c.value
        ]

        comp_summary = ", ".join(
            f"{c.ref or '?'}={c.value}" for c in physical_comps[:5]
        ) or "no validated components"
        net_summary = ", ".join(net_labels[:5]) or "no identified nets"

        # Targeted query: device + section + specific check + observed facts
        query = (
            f"TLE987x {selected_section.replace('_', ' ')} "
            f"component requirements {comp_summary} nets {net_summary}"
        )

        # --- RAG Retrieval ---
        results = []
        retriever_error = None
        try:
            results = self.retriever.search(query=query, top_k=3)
        except Exception as e:
            retriever_error = str(e)
            safe_print(f"[VERIFIER] HybridRetriever error: {e}")

        # Safety rule: no retrieval → INSUFFICIENT_INPUT
        if retriever_error or not results:
            return FindingItem(
                check_id="R5",
                category="engineering",
                check_name="Reference Requirement Comparison",
                status=CheckResultState.INSUFFICIENT_INPUT,
                schematic_evidence=SchematicEvidence(
                    components=[{"ref": c.ref, "value": c.value} for c in physical_comps]
                ),
                decision_reasoning=(
                    f"Reference retrieval returned no evidence for '{selected_section}'. "
                    + (f"Retriever error: {retriever_error}" if retriever_error else
                       "No matching document sections found. Cannot evaluate requirements.")
                )
            )

        # Build reference text block
        ref_blocks = []
        for idx, r in enumerate(results, 1):
            ref_blocks.append(
                f"[Source {idx} — Page {r.unit.page_start}, Sec {r.unit.section_number}]\n"
                f"{r.unit.text_content.strip()}"
            )
        ref_text = "\n\n".join(ref_blocks)

        top_res = results[0]
        ref_evidence = ReferenceEvidence(
            document="TLE987x/6x Hardware Design Guideline",
            page=top_res.unit.page_start,
            section=top_res.unit.section_number,
            unit_id=top_res.unit_id,
            source_text=top_res.unit.text_content[:300]
        )

        # --- LLM Comparison ---
        user_prompt = (
            f"Device: TLE987x\n"
            f"Confirmed Section: {selected_section}\n"
            f"Observed Physical Components: {comp_summary}\n"
            f"Observed Net Labels: {net_summary}\n\n"
            f"Retrieved Reference Evidence:\n{ref_text}"
        )

        # Default is NEEDS_REVIEW — never PASS
        status = CheckResultState.NEEDS_REVIEW
        reasoning = (
            "Reference evidence was retrieved but LLM comparison could not be completed. "
            "Manual review required."
        )

        try:
            llm_raw = call_mistral_text(
                system_prompt=R5_COMPARISON_SYSTEM_PROMPT,
                user_prompt=user_prompt
            )
            if llm_raw and "{" in llm_raw and "}" in llm_raw:
                json_str = llm_raw[llm_raw.find("{"):llm_raw.rfind("}") + 1]
                parsed = json.loads(json_str)
                status_str = parsed.get("status", "NEEDS_REVIEW").upper()
                if status_str in CheckResultState.__members__:
                    status = CheckResultState(status_str)
                reasoning = parsed.get("reason", reasoning)
            elif llm_raw:
                reasoning = llm_raw.strip()
        except MistralAPIError as e:
            safe_print(f"[VERIFIER] LLM API error: {e}")
            # LLM failure → NEEDS_REVIEW (already set as default)
        except Exception as e:
            safe_print(f"[VERIFIER] LLM parse error: {e}")
            # Parse failure → NEEDS_REVIEW (already set as default)

        return FindingItem(
            check_id="R5",
            category="engineering",
            check_name="Reference Requirement Comparison",
            status=status,
            schematic_evidence=SchematicEvidence(
                components=[{"ref": c.ref, "value": c.value} for c in physical_comps]
            ),
            reference_evidence=ref_evidence,
            decision_reasoning=reasoning
        )
