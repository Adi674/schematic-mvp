"""
Pipeline Orchestrator.
Executes the state pipeline: Router -> (Exact Lookup / RAG Retrieve / Extract -> Normalize -> Rule Engine) -> Composer -> Sanity Check.
"""

import sqlite3
import os
from typing import Dict, Any
from src.graph.state import PipelineState
from src.graph.nodes.router import router_node
from src.graph.nodes.extract import extract_schematic_node
from src.graph.nodes.rule_engine import run_rule_engine, get_db_connection
from src.graph.nodes.composer import composer_node
from src.graph.nodes.sanity_check import sanity_check_node
from src.rag import search_doc_chunks


def run_pipeline(question: str, image: bytes = None) -> PipelineState:
    print(f"\n{'#'*35} [PIPELINE EXECUTION START] {'#'*35}")
    print(f"Question: \"{question}\"")
    print(f"Image attached: {'YES (' + str(len(image)) + ' bytes)' if image else 'NO'}")

    state: PipelineState = {
        "question": question,
        "image": image,
        "routes": [],
        "matched_symbol": None,
        "inferred_domain": None,
        "exact_match_result": None,
        "retrieved_chunks": [],
        "extracted_components": [],
        "normalized_components": [],
        "rule_engine_results": [],
        "final_answer": "",
        "checklist_report": [],
        "sanity_flags": []
    }

    # 1. Router Node — determines routes, matched symbol, and domain
    router_out = router_node(state)
    state["routes"] = router_out["routes"]
    state["matched_symbol"] = router_out.get("matched_symbol")
    state["inferred_domain"] = router_out.get("inferred_domain")

    print(f"\n[ROUTER OUTPUT] Active Routes: {state['routes']} | Matched Symbol: {state['matched_symbol']} | Domain: {state['inferred_domain']}")

    # 2. Execution Paths
    if "exact_lookup" in state["routes"]:
        matched_symbol = state.get("matched_symbol")
        if matched_symbol:
            conn = get_db_connection()
            cursor = conn.cursor()
            # Search by the extracted symbol or pin — not the whole question
            cursor.execute(
                "SELECT * FROM rules WHERE UPPER(symbol) = UPPER(?) OR UPPER(pin) = UPPER(?)",
                (matched_symbol, matched_symbol)
            )
            row = cursor.fetchone()
            if row:
                state["exact_match_result"] = dict(row)
                print(f"[EXACT LOOKUP MATCH] Found rule for '{matched_symbol}': Rule ID: {row['rule_id']}, Domain: {row['domain']}, Min: {row['min_value_SI']}, Max: {row['max_value_SI']}")
            else:
                print(f"[EXACT LOOKUP] No direct rule in rules.db for '{matched_symbol}'")
            conn.close()

    if "rag" in state["routes"]:
        # Pass domain from router for metadata-filtered retrieval
        domain = state.get("inferred_domain")
        chunks = search_doc_chunks(question, domain=domain, top_k=3)
        state["retrieved_chunks"] = chunks

    if "extraction" in state["routes"]:
        ext_out = extract_schematic_node(state)
        state["extracted_components"] = ext_out["extracted_components"]
        state["normalized_components"] = ext_out["normalized_components"]

        # Run Rule Engine on extracted components
        rule_results = run_rule_engine(state["normalized_components"])
        state["rule_engine_results"] = rule_results
        print(f"\n[RULE ENGINE VERDICTS] Evaluated {len(rule_results)} component(s):")
        for r in rule_results:
            print(f"  - {r['component']} (Pin: {r['pin']}) -> Status: {r['status']} | Expected: {r['expected']} | Actual: {r['actual']} | Reason: {r['reason']}")

    # 3. Composer Node
    comp_out = composer_node(state)
    state["final_answer"] = comp_out["final_answer"]
    state["checklist_report"] = comp_out["checklist_report"]

    # 4. Sanity Check Node
    sanity_out = sanity_check_node(state)
    state["sanity_flags"] = sanity_out["sanity_flags"]
    if state["sanity_flags"]:
        print(f"[SANITY FLAGS] {state['sanity_flags']}")

    print(f"\n{'#'*35} [PIPELINE EXECUTION COMPLETE] {'#'*35}\n")
    return state

