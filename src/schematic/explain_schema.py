"""
Response schemas for Scenario A — "Explain this schematic" (WS4).

Kept separate from schema.py's FindingItem/ReviewCropResponse deliberately:
those are checklist-shaped (PASS/FAIL/etc against a fixed check_id) and
belong to the older single-pass review framework. Explaining a component
is not a pass/fail check — it's a per-component narrative with a citation,
so it gets its own response shape.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

from src.schematic.schema import ReferenceEvidence


class ComponentExplanation(BaseModel):
    """One resolved component's explanation, grounded in HDG evidence."""
    component_label: str
    net_name: Optional[str] = None
    function: Optional[str] = None
    domain: Optional[str] = None
    resolution: str = Field(
        default="unresolved",
        description="'direct_pin' | 'graph_walk' | 'unresolved' — from ComponentResolution.primary",
    )
    explanation: str
    reference_evidence: List[ReferenceEvidence] = Field(default_factory=list)
    insufficient_evidence: bool = Field(
        default=False,
        description="True if no reference evidence was retrieved for this component — "
        "explanation text will say so rather than inventing a specification.",
    )


class ExplainCropResponse(BaseModel):
    review_id: str
    device_context: Optional[str] = None
    component_explanations: List[ComponentExplanation] = Field(default_factory=list)
    narrative: str = Field(
        default="",
        description="Single coherent explanation rolling up all component_explanations.",
    )