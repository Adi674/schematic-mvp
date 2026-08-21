from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class SemanticEvidence(BaseModel):
    bbox: Optional[List[float]] = None
    model_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SemanticComponent(BaseModel):
    label: Optional[str] = None
    label_state: Literal[
        "VISIBLE",
        "UNREADABLE",
        "NOT_VISIBLE",
        "UNKNOWN"
    ] = "UNKNOWN"

    type: Optional[str] = None
    function: Optional[str] = None

    value: Optional[str] = None
    value_state: Literal[
        "VISIBLE",
        "UNREADABLE",
        "NOT_VISIBLE",
        "UNKNOWN"
    ] = "UNKNOWN"

    evidence: Optional[SemanticEvidence] = None
    geometry_verified: Optional[bool] = None
    


class SemanticNode(BaseModel):
    name: str
    description: Optional[str] = None
    evidence: Optional[SemanticEvidence] = None


class SemanticConnection(BaseModel):
    source: str
    target: str

    relationship: Literal[
        "connected_to",
        "feeds",
        "connected_between",
        "supplies",
        "unknown"
    ] = "unknown"

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: Optional[SemanticEvidence] = None

class SemanticUncertainty(BaseModel):
    description: str
    related_objects: List[str] = Field(default_factory=list)


class SemanticSchematic(BaseModel):
    schema_version: str = "1.0"

    image_id: str
    width: int
    height: int

    device_context: Optional[str] = None

    components: List[SemanticComponent] = Field(default_factory=list)
    nodes: List[SemanticNode] = Field(default_factory=list)
    connections: List[SemanticConnection] = Field(default_factory=list)

    uncertainties: List[SemanticUncertainty] = Field(default_factory=list)

class SemanticCropResponse(BaseModel):
    review_id: str
    model: str
    extraction: SemanticSchematic