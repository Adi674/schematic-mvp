"""
Retrieval Schema — Pydantic v2 schemas for Retrieval Units and Evaluation Queries.
"""

from __future__ import annotations

import enum
from typing import Literal, Optional
from pydantic import BaseModel, Field


class RetrievalUnitType(str, enum.Enum):
    section_prose = "section_prose"
    table_row = "table_row"
    table_summary = "table_summary"
    figure_context = "figure_context"
    equation_definition = "equation_definition"


class RetrievalUnit(BaseModel):
    unit_id: str
    unit_type: RetrievalUnitType
    document_id: str
    document_version: str
    section_id: str
    section_number: str
    section_title: str
    domain: str
    page_start: int
    page_end: int
    text_content: str
    source_object_ids: list[str] = Field(default_factory=list)
    source_hashes: list[str] = Field(default_factory=list)
    bbox: list[float] = Field(default_factory=list)


class QueryResult(BaseModel):
    unit_id: str
    score: float
    rank: int
    retrieval_method: str = "hybrid"  # dense, lexical, hybrid
    unit: RetrievalUnit
    bbox: list[float] = Field(default_factory=list)
    source_object_ids: list[str] = Field(default_factory=list)
    object_source_hash: str = ""
    document_hash: str = ""


class QueryType(str, enum.Enum):
    exact_symbol = "exact_symbol"
    conceptual = "conceptual"
    identifier = "identifier"
    multi_term = "multi_term"
    figure = "figure"
    equation = "equation"
    paraphrased = "paraphrased"
    multi_component = "multi_component"
    numerical = "numerical"
    table_oriented = "table_oriented"
    adversarial_near_neighbor = "adversarial_near_neighbor"


class EvalQuestion(BaseModel):
    id: str
    query: str
    query_type: QueryType
    category: str = ""
    domain: str
    expected_section: str
    expected_page: int
    expected_source_objects: list[str] = Field(default_factory=list)
    expected_unit_type: Optional[RetrievalUnitType] = None
