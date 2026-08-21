"""
Data schemas for Schematic Crop Review MVP.

Revision history:
  v0.2 — Object taxonomy, bbox validation, dual confidence, ref_state, wire geometry.
"""

from enum import Enum
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Fact State & Object Types
# ---------------------------------------------------------------------------

class FactState(str, Enum):
    VALIDATED = "VALIDATED"
    UNKNOWN = "UNKNOWN"
    UNREADABLE = "UNREADABLE"
    NOT_VISIBLE = "NOT_VISIBLE"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID_GEOMETRY = "INVALID_GEOMETRY"


class RefState(str, Enum):
    """Whether the reference designator was visibly printed or inferred."""
    VISIBLE = "VISIBLE"
    UNREADABLE = "UNREADABLE"
    NOT_VISIBLE = "NOT_VISIBLE"
    INFERRED = "INFERRED"  # Model guessed it — must not be treated as a fact


class ValidationStatus(str, Enum):
    """Post-processing validation result for a fact, independent of model confidence."""
    OK = "OK"
    INVALID_GEOMETRY = "INVALID_GEOMETRY"
    DUPLICATE_REF = "DUPLICATE_REF"
    INCONSISTENT = "INCONSISTENT"
    UNVERIFIED = "UNVERIFIED"


class SchematicObjectType(str, Enum):
    """Unified object taxonomy for all visible schematic objects."""
    PHYSICAL_COMPONENT = "PHYSICAL_COMPONENT"   # capacitor, resistor, diode, inductor, crystal...
    IC_DEVICE = "IC_DEVICE"                     # integrated circuit, MCU
    FUNCTIONAL_BLOCK = "FUNCTIONAL_BLOCK"       # PMU, PSG, Power-down supply (block symbols)
    NET_LABEL = "NET_LABEL"                     # VDDP, GND, LIN — text labels on wires
    POWER_SYMBOL = "POWER_SYMBOL"               # VCC / GND rail symbols
    TERMINAL = "TERMINAL"                       # device pin or connector terminal
    WIRE = "WIRE"                               # electrical wire segment
    JUNCTION = "JUNCTION"                       # wire junction dot
    ANNOTATION = "ANNOTATION"                   # notes, dimensions, non-electrical text
    UNKNOWN_OBJECT = "UNKNOWN_OBJECT"


# ---------------------------------------------------------------------------
# Bounding Box Evidence
# ---------------------------------------------------------------------------

def validate_bbox(
    bbox: Optional[List[float]],
    image_width: int,
    image_height: int
) -> Tuple[bool, str]:
    """
    Validates a bbox in canonical [x1, y1, x2, y2] format.
    Returns (is_valid, reason_if_invalid).
    """
    if bbox is None:
        return False, "bbox is None"
    if len(bbox) != 4:
        return False, f"bbox has {len(bbox)} elements, expected 4"
    x1, y1, x2, y2 = bbox
    if x1 < 0 or y1 < 0:
        return False, f"negative coordinates: x1={x1}, y1={y1}"
    if x2 > image_width or y2 > image_height:
        return False, f"out of image bounds: x2={x2}>w={image_width} or y2={y2}>h={image_height}"
    if x1 >= x2 or y1 >= y2:
        return False, f"degenerate bbox: x1={x1}>=x2={x2} or y1={y1}>=y2={y2}"
    return True, ""


class BoundingBoxEvidence(BaseModel):
    """
    Bounding box evidence in canonical [x1, y1, x2, y2] image-pixel format.
    bbox_validated is only set True after passing validate_bbox().
    """
    bbox: Optional[List[float]] = Field(default=None, description="[x1, y1, x2, y2] in image pixels")
    coordinate_space: str = "image_pixels"
    model_confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Raw VLM-reported confidence")
    validation_status: ValidationStatus = ValidationStatus.UNVERIFIED
    source: str = "mistral_vision"
    bbox_validated: bool = False


# ---------------------------------------------------------------------------
# Physical Component Fact
# ---------------------------------------------------------------------------

class ComponentFact(BaseModel):
    """A physically identifiable electrical component or schematic object."""
    object_type: SchematicObjectType = SchematicObjectType.UNKNOWN_OBJECT
    ref: Optional[str] = Field(default=None, description="Reference designator e.g. C15, U1")
    ref_state: RefState = RefState.NOT_VISIBLE
    type: str = Field(default="unknown", description="Component sub-type e.g. capacitor, resistor, IC")
    value: Optional[str] = Field(default=None, description="Component value e.g. '100 nF', '10 k'")
    value_state: FactState = FactState.UNKNOWN  # Default UNKNOWN — not VALIDATED
    evidence: Optional[BoundingBoxEvidence] = None
    model_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    validation_status: ValidationStatus = ValidationStatus.UNVERIFIED

    @property
    def effective_confidence(self) -> float:
        """Effective confidence = 0 if geometry invalid, else model_confidence."""
        if self.validation_status == ValidationStatus.INVALID_GEOMETRY:
            return 0.0
        return self.model_confidence


# ---------------------------------------------------------------------------
# Pin / Terminal Fact
# ---------------------------------------------------------------------------

class PinFact(BaseModel):
    component_ref: str = Field(description="Ref designator of the owning component")
    pin_number: Optional[str] = Field(default=None)
    pin_name: Optional[str] = Field(default=None)
    evidence: Optional[BoundingBoxEvidence] = None
    model_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    validation_status: ValidationStatus = ValidationStatus.UNVERIFIED


# ---------------------------------------------------------------------------
# Net Facts
# ---------------------------------------------------------------------------

class NetFact(BaseModel):
    net_id: str = Field(description="Unique net ID e.g. NET_001")
    name: Optional[str] = Field(default=None, description="Visible label e.g. VDDP, GND")
    source: str = Field(default="geometry", description="'geometry' | 'llm_inferred'")
    model_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class NetMembershipFact(BaseModel):
    net_id: str
    members: List[str] = Field(
        default_factory=list,
        description="Pin identifiers belonging to this net e.g. ['C15.1', 'U1.VDDP']"
    )
    source: str = Field(default="geometry", description="'geometry' | 'llm_inferred'")
    model_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Wire & Junction Facts
# ---------------------------------------------------------------------------

class WireSegmentFact(BaseModel):
    wire_id: str
    start: Optional[List[float]] = Field(default=None, description="[x, y] start pixel")
    end: Optional[List[float]] = Field(default=None, description="[x, y] end pixel")
    points: List[List[float]] = Field(default_factory=list, description="Polyline points [[x,y],...]")
    connected_net_id: Optional[str] = None
    source: str = Field(default="geometry", description="'geometry' | 'llm_description'")
    model_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    validation_status: ValidationStatus = ValidationStatus.UNVERIFIED


class JunctionFact(BaseModel):
    junction_id: str
    position: Optional[List[float]] = Field(default=None, description="[x, y] pixel position")
    connected_wires: List[str] = Field(default_factory=list)
    source: str = Field(default="geometry", description="'geometry' | 'llm_description'")


class ConnectionUncertainty(BaseModel):
    description: str
    related_pins: List[str] = Field(default_factory=list)
    related_wires: List[str] = Field(default_factory=list)
    reason: FactState = FactState.AMBIGUOUS


# ---------------------------------------------------------------------------
# Image Input & Root Container
# ---------------------------------------------------------------------------

class ImageInputInfo(BaseModel):
    image_id: str
    width: int
    height: int
    crop_scope: str = Field(default="partial", description="'partial' or 'full'")
    mime_type: str = Field(default="image/png")


class SchematicFacts(BaseModel):
    schema_version: str = "0.2"
    input_info: ImageInputInfo
    device_context: Optional[str] = None
    components: List[ComponentFact] = Field(default_factory=list)
    pins: List[PinFact] = Field(default_factory=list)
    nets: List[NetFact] = Field(default_factory=list)
    net_memberships: List[NetMembershipFact] = Field(default_factory=list)
    wires: List[WireSegmentFact] = Field(default_factory=list)
    junctions: List[JunctionFact] = Field(default_factory=list)
    labels: List[Dict[str, Any]] = Field(default_factory=list)
    uncertainties: List[ConnectionUncertainty] = Field(default_factory=list)
    geometry_stage_applied: bool = Field(
        default=False,
        description="True if OpenCV geometry stage was run on this image"
    )


# ---------------------------------------------------------------------------
# Section Catalog & Candidates
# ---------------------------------------------------------------------------

class SectionDefinition(BaseModel):
    section_id: str
    parent_section_id: Optional[str] = None   # For hierarchy support
    name: str
    key_pins: List[str] = Field(default_factory=list)
    typical_components: List[str] = Field(default_factory=list)
    typical_nets: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)


class SectionCandidate(BaseModel):
    section_id: str
    name: str
    match_score: float = Field(ge=0.0, le=1.0, description="Raw additive match score")
    confidence_calibrated: bool = False  # Always False until benchmark calibration
    matched_evidence: List[str] = Field(default_factory=list)
    parent_section_id: Optional[str] = None


class SectionEvidencePacket(BaseModel):
    device_context: Optional[str] = None
    high_confidence_components: List[Dict[str, str]] = Field(default_factory=list)
    visible_values: List[str] = Field(default_factory=list)
    named_pins: List[str] = Field(default_factory=list)
    named_nets: List[str] = Field(default_factory=list)
    net_memberships: List[Dict[str, Any]] = Field(default_factory=list)
    net_labels: List[str] = Field(default_factory=list)   # From NET_LABEL objects


# ---------------------------------------------------------------------------
# Checklist & Findings
# ---------------------------------------------------------------------------

class CheckResultState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    NOT_CHECKED = "NOT_CHECKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class SchematicEvidence(BaseModel):
    components: List[Dict[str, Any]] = Field(default_factory=list)
    pins: List[Dict[str, Any]] = Field(default_factory=list)
    net_connections: List[Dict[str, Any]] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)


class ReferenceEvidence(BaseModel):
    document: str = "TLE987x/6x Hardware Design Guideline"
    page: Optional[int] = None
    section: Optional[str] = None
    unit_id: Optional[str] = None
    source_text: Optional[str] = None


class FindingItem(BaseModel):
    check_id: str
    category: str = Field(description="'extraction' or 'engineering'")
    check_name: str
    status: CheckResultState
    schematic_evidence: SchematicEvidence
    reference_evidence: Optional[ReferenceEvidence] = None
    decision_reasoning: str


# ---------------------------------------------------------------------------
# API Request / Response Contracts
# ---------------------------------------------------------------------------

class ParseCropResponse(BaseModel):
    review_id: str
    extraction: SchematicFacts
    section_candidates: List[SectionCandidate]
    needs_confirmation: bool
    suggested_section: Optional[str] = None


class ReviewCropRequest(BaseModel):
    selected_section: str


class ReviewCropResponse(BaseModel):
    review_id: str
    selected_section: str
    findings: List[FindingItem]
    summary_status: CheckResultState
