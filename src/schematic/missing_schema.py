"""
Response schemas for Scenario B — "What's missing" (WS5).

Presence-only diff: for each net the customer's crop actually touches, checks
whether the reference schematic's expected component types on that net are
present in the extraction. Explicitly NOT a topology/placement check (FR-017
stays out of scope per the plan) — this only asks "is a component of the
right type present," never "is it wired in the right order."
"""

from typing import List, Optional
from pydantic import BaseModel, Field

from src.schematic.schema import ReferenceEvidence


class MissingComponentFinding(BaseModel):
    expected_ref: str
    expected_type: str
    net_name: str
    section: Optional[str] = None
    function: Optional[str] = None
    status: str = Field(description="'PRESENT' | 'MISSING'")
    matched_component_label: Optional[str] = None
    reasoning: str
    reference_evidence: List[ReferenceEvidence] = Field(default_factory=list)
    insufficient_evidence: bool = False


class MissingCropResponse(BaseModel):
    review_id: str
    device_context: Optional[str] = None
    reference_device: Optional[str] = Field(
        default=None,
        description="Which reference schematic file this crop was diffed against.",
    )
    nets_checked: List[str] = Field(default_factory=list)
    findings: List[MissingComponentFinding] = Field(default_factory=list)
    summary: str = Field(
        default="",
        description="Short rollup, e.g. '2 of 9 expected components missing on checked nets.'",
    )