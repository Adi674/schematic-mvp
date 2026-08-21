"""
Composer Node (Mistral Small Text Integration).
Merges RAG chunks, exact DB lookups, pinout metadata, and rule engine verdicts into a rich natural language response.
Strict constraint: Never override or invent a numeric verdict.
"""

from typing import Dict, Any
from src.graph.state import PipelineState
from src.rag import get_chunk_by_id
from src.llm import call_mistral_text
from src.data.pinout import PINOUT_DATA

COMPOSER_SYSTEM_PROMPT = """
You are an expert Infineon MOTIX TLE987x/6x Microcontroller Hardware Design Review Assistant.

Your task is to provide a helpful, professional, and precise Markdown response that DIRECTLY answers the User's Question.

CRITICAL INSTRUCTIONS:
1. INTENT-FOCUSED ANSWERING:
   - Always read the User Question carefully and address what was explicitly requested.
   - If the user asks for "components and pins in this diagram" or "what components are shown":
     * Clearly list the extracted components, their designated pins, and nets from the diagram.
     * If compliance rule results are available, present them concisely with their recommended specification.
     * Do NOT dump unasked general MCU information (like SWD pins, unused pins, or PCB layout) unless requested.
   - If the user asks for a "review" or "compliance check":
     * Present the structured compliance verification table with PASS / FAIL / NEEDS_INPUT statuses and reasons.
   - If the user asks an explanatory question (e.g., "Why is C_LIN needed?"):
     * Explain the engineering rationale citing the specific chapter/table.
   - If the user asks about MCU package/pinout specs (e.g. "How many pins?"):
     * State the package details (e.g. 48 pins in VQFN-48 / TQFP-48).

2. GROUND TRUTH VERDICTS:
   - NEVER alter, override, or invent numeric PASS / MARGINAL / FAIL / NEEDS_INPUT verdicts.
   - If a component has status "NEEDS_INPUT" (e.g. value is not printed on the schematic diagram), clearly explain:
     "Component is present in the diagram, but its numerical value is not labeled. The hardware guideline requires: <Expected Spec>."

3. ZERO UNRELATED HALLUCINATION:
   - ONLY discuss topics, components, and guideline chapters that are directly relevant to the user's query and the active circuit components.
   - Do NOT include random sections about unrelated peripherals.

4. CLEAN MARKDOWN FORMATTING:
   - Use clear headers, tables, and bullet points. Avoid long repetitive boilerplate intros.
"""


def composer_node(state: PipelineState) -> Dict[str, Any]:
    question = state.get("question", "")
    rule_results = state.get("rule_engine_results", [])
    retrieved_chunks = state.get("retrieved_chunks", [])
    exact_result = state.get("exact_match_result")
    routes = state.get("routes", [])

    # Build structured context string for Mistral LLM
    context_parts = [f"User Question: {question}\n"]

    # Only include MCU package metadata when the user is explicitly asking about package/pinout specs
    q_lower = question.lower()
    is_package_question = any(kw in q_lower for kw in ["package", "vqfn", "tqfp", "total pins", "pin count", "how many pins", "package specification", "pinout"])
    if is_package_question:
        context_parts.append(f"MCU Package Specification: {PINOUT_DATA['chip_family']} comes in a {PINOUT_DATA['package']} package with {PINOUT_DATA['total_pins']} total physical pins.")

    if rule_results:
        context_parts.append("\nExtracted Components & Rule Engine Results:")
        for r in rule_results:
            context_parts.append(f"- Component: {r['component']}, Pin: {r['pin']}, Status: {r['status']}, Actual in Diagram: {r['actual']}, Guideline Requirement: {r['expected']}, Reason: {r['reason']}")
            source = r.get("source")
            if source and "chunk_id" in source:
                chunk = get_chunk_by_id(source["chunk_id"])
                if chunk:
                    context_parts.append(f"  Guideline Reference ({source['table']}, Page {source['page']}): {chunk['text']}")

    if exact_result:
        context_parts.append(f"\nExact Rule Lookup for {exact_result['symbol']}:")
        context_parts.append(f"- Pin: {exact_result['pin']}, Domain: {exact_result['domain']}, Min: {exact_result['min_value_SI']}, Max: {exact_result['max_value_SI']} {exact_result['unit']}, Dielectric: {exact_result.get('dielectric_required')}, Source: {exact_result['source_table']} Page {exact_result['source_page']}")

    # Only include retrieved RAG chunks if RAG was an active route
    if retrieved_chunks and "rag" in routes:
        context_parts.append("\nRetrieved Hardware Guideline Context:")
        for c in retrieved_chunks:
            context_parts.append(f"- Chapter {c['chapter_num']} ({c['title']}): {c['text']}")

    user_prompt = "\n".join(context_parts)

    # Call Mistral Small LLM for natural language composition
    mistral_answer = call_mistral_text(COMPOSER_SYSTEM_PROMPT, user_prompt)

    # If Mistral API key is set and call succeeds, use LLM response
    if mistral_answer:
        final_answer = mistral_answer
    else:
        # Clean Structured Fallback Response
        answer_parts = []

        if is_package_question:
            answer_parts.append(f"### TLE987x/6x Package & Pin Specification\n")
            answer_parts.append(f"- **Chip Family**: {PINOUT_DATA['chip_family']}")
            answer_parts.append(f"- **Package**: {PINOUT_DATA['package']} (and TQFP-48)")
            answer_parts.append(f"- **Total Pins**: **{PINOUT_DATA['total_pins']} physical pins** (Pins 1 to 48)\n")

        if rule_results:
            answer_parts.append("### Schematic Components & Compliance Summary\n")
            answer_parts.append("| Component | Pin | Status | Guideline Spec | Actual in Diagram | Note |")
            answer_parts.append("|---|---|---|---|---|---|")
            for res in rule_results:
                answer_parts.append(f"| {res['component']} | {res['pin']} | **{res['status']}** | {res['expected']} | {res['actual']} | {res['reason']} |")
            answer_parts.append("\n")

        elif exact_result:
            answer_parts.append(f"### Rule Spec for `{exact_result['symbol']}` ({exact_result['domain']} Domain)")
            answer_parts.append(f"- **Pin**: {exact_result['pin']}")
            answer_parts.append(f"- **Min Value**: {exact_result['min_value_SI']} {exact_result['unit']}")
            answer_parts.append(f"- **Max Value**: {exact_result['max_value_SI']} {exact_result['unit']}")
            if exact_result.get("dielectric_required"):
                answer_parts.append(f"- **Dielectric Required**: {exact_result['dielectric_required']}")
            answer_parts.append(f"- **Source**: {exact_result['source_table']} (Page {exact_result['source_page']})\n")

        elif retrieved_chunks:
            answer_parts.append("### Relevant Hardware Guidelines\n")
            for chunk in retrieved_chunks:
                answer_parts.append(f"#### Chapter {chunk['chapter_num']}: {chunk['title']}")
                answer_parts.append(f"{chunk['text']}\n")

        final_answer = "\n".join(answer_parts)

    return {
        "final_answer": final_answer,
        "checklist_report": rule_results
    }
