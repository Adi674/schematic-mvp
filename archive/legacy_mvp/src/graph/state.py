"""
LangGraph State Definition.
Explicit TypedDict maintaining state across router, extraction, RAG, rule engine, composer, and sanity check nodes.
"""

from typing import List, Dict, Any, Optional, Literal
from typing_extensions import TypedDict


class PipelineState(TypedDict):
    question: str
    image: Optional[bytes]
    routes: List[Literal["exact_lookup", "rag", "extraction"]]

    # Router outputs
    matched_symbol: Optional[str]
    inferred_domain: Optional[str]

    # Exact lookup path
    exact_match_result: Optional[Dict[str, Any]]

    # RAG path
    retrieved_chunks: List[Dict[str, Any]]

    # Extraction path
    extracted_components: List[Dict[str, Any]]
    normalized_components: List[Dict[str, Any]]
    rule_engine_results: List[Dict[str, Any]]

    # Final output
    final_answer: str
    checklist_report: List[Dict[str, Any]]
    sanity_flags: List[str]
