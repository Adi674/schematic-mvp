"""
Crop Handler — single-call entry point for chat-style usage.

Collapses the two-call flow (parse_crop then explain_crop/review_crop) into
one call: image + a free-text message in, extraction + routed result out.
No server-side review session state is required for this path since nothing
needs to be recalled across turns — each chat turn re-sends the crop.

Routing note: this is a fixed keyword router between two KNOWN scenarios
(explain vs. missing-check), not an open-ended intent classifier. The plan
explicitly scopes "Intent/request classifier" out of the MVP — that refers to
a general NLU system for arbitrary requests, not this. If a real classifier
is ever wanted, this is the function to replace.
"""

from __future__ import annotations

import uuid
from typing import Optional, Literal

from src.retrieval.hybrid_retriever import HybridRetriever
from src.schematic.semantic_extractor import SemanticSchematicExtractor
from src.schematic.net_resolution import load_pin_index
from src.schematic.explain_service import explain_schematic
from src.schematic.explain_schema import ExplainCropResponse
from src.schematic.missing_check_service import check_missing_components
from src.schematic.missing_schema import MissingCropResponse

Intent = Literal["explain", "missing"]

_MISSING_KEYWORDS = (
    "missing", "what's not", "whats not", "not present", "complete",
    "requirement", "required", "anything left out", "review this",
    "check this", "compliant", "compliance",
)
_EXPLAIN_KEYWORDS = (
    "explain", "what is", "what does", "describe", "function of",
    "tell me about", "walk me through",
)


def classify_intent(message: str) -> Intent:
    """Simple keyword router — see module docstring for why this is not the
    out-of-scope 'intent classifier'. Defaults to 'explain' on anything
    ambiguous: explain always has grounded output regardless of whether a
    reference schematic exists for this device, so it's the safer default."""
    text = (message or "").lower()
    if any(k in text for k in _MISSING_KEYWORDS):
        return "missing"
    if any(k in text for k in _EXPLAIN_KEYWORDS):
        return "explain"
    return "explain"


def handle_crop_message(
    image_bytes: bytes,
    message: str,
    filename: str = "crop.png",
    width: int = 800,
    height: int = 600,
    device_hint: Optional[str] = None,
    mime_type: str = "image/png",
    semantic_extractor: Optional[SemanticSchematicExtractor] = None,
    retriever: Optional[HybridRetriever] = None,
    pin_index_path: str = "data/pinout_map/tle987x_pinout.json",
) -> dict:
    """One call: extract -> route by message intent -> explain or missing-check.

    Returns a plain dict rather than a single Pydantic model since the two
    branches (ExplainCropResponse / MissingCropResponse) have different
    shapes — the API layer wraps this in whichever response_model matches
    the returned "intent".
    """
    semantic_extractor = semantic_extractor or SemanticSchematicExtractor()
    retriever = retriever or HybridRetriever()
    review_id = str(uuid.uuid4())

    semantic = semantic_extractor.extract(
        image_bytes=image_bytes,
        image_id=filename,
        width=width,
        height=height,
        mime_type=mime_type,
        device_hint=device_hint,
    )

    intent = classify_intent(message)

    if intent == "missing":
        pin_index = load_pin_index(pin_index_path)  # unused directly by WS5 today, kept for
        # symmetry / future net-domain-aware missing checks
        result: MissingCropResponse = check_missing_components(
            semantic=semantic,
            retriever=retriever,
            review_id=review_id,
        )
    else:
        pin_index = load_pin_index(pin_index_path)
        result: ExplainCropResponse = explain_schematic(
            semantic=semantic,
            pin_index=pin_index,
            retriever=retriever,
            review_id=review_id,
        )

    return {
        "review_id": review_id,
        "intent": intent,
        "extraction": semantic,
        "result": result,
    }

    