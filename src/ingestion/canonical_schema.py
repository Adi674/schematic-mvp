"""
Canonical Knowledge Model — Pydantic v2 schemas for the hierarchical document representation.

Hierarchy:
    CanonicalDocument
     └── sections: list[Section]
          └── content_blocks: list[ContentBlock]  (ordered by `order`)
               ├── ProseBlock
               ├── Table
               │    └── rows: list[TableRow]
               ├── Figure
               ├── Equation
               └── DefinitionBlock

Every content object carries:
  - raw source text (never modified)
  - normalized text (cleaned for downstream use)
  - full traceability (document_hash, object_source_hash, page, bbox)
  - extraction_status + confidence
"""

from __future__ import annotations

import hashlib
import enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, computed_field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ExtractionStatus(str, enum.Enum):
    validated = "validated"
    needs_review = "needs_review"


# ---------------------------------------------------------------------------
# Document metadata
# ---------------------------------------------------------------------------

class DocumentMetadata(BaseModel):
    document_id: str
    document_version: str
    title: str
    manufacturer: str = ""
    product_family: str = ""
    date: str = ""
    page_count: int = 0
    document_hash: str = ""  # SHA-256 of the original PDF file


# ---------------------------------------------------------------------------
# Traceability
# ---------------------------------------------------------------------------

class Traceability(BaseModel):
    document_id: str
    document_version: str
    page: int
    bbox: list[float] = Field(default_factory=list)  # [x0, y0, x1, y1]
    object_id: str
    parent_id: str = ""
    source_text: str = ""
    object_source_hash: str = ""  # SHA-256 of raw object text
    document_hash: str = ""       # SHA-256 of the original PDF file


# ---------------------------------------------------------------------------
# Content blocks — base
# ---------------------------------------------------------------------------

class ContentBlockBase(BaseModel):
    object_id: str
    type: str
    section_id: str = ""
    order: int = 0  # reading-order index within the section
    page: int = 0
    traceability: Traceability | None = None
    extraction_status: ExtractionStatus = ExtractionStatus.validated
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# Prose
# ---------------------------------------------------------------------------

class ProseBlock(ContentBlockBase):
    type: Literal["prose"] = "prose"
    raw_text: str = ""
    normalized_text: str = ""


# ---------------------------------------------------------------------------
# Table row
# ---------------------------------------------------------------------------

class TableRow(BaseModel):
    object_id: str
    table_id: str = ""
    order: int = 0
    raw_cells: dict[str, str] = Field(default_factory=dict)
    normalized_cells: dict[str, str] = Field(default_factory=dict)
    traceability: Traceability | None = None
    extraction_status: ExtractionStatus = ExtractionStatus.validated
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

class Table(ContentBlockBase):
    type: Literal["table"] = "table"
    table_id: str = ""
    title: str = ""
    headers_raw: list[str] = Field(default_factory=list)
    headers_normalized: list[str] = Field(default_factory=list)
    rows: list[TableRow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Figure
# ---------------------------------------------------------------------------

class Figure(ContentBlockBase):
    type: Literal["figure"] = "figure"
    figure_id: str = ""
    caption: str = ""
    image_path: str = ""
    nearby_text: str = ""


# ---------------------------------------------------------------------------
# Equation
# ---------------------------------------------------------------------------

class Equation(ContentBlockBase):
    type: Literal["equation"] = "equation"
    raw_text: str = ""
    normalized_text: str = ""


# ---------------------------------------------------------------------------
# Definition block
# ---------------------------------------------------------------------------

class DefinitionBlock(ContentBlockBase):
    type: Literal["definition_block"] = "definition_block"
    raw_text: str = ""
    normalized_text: str = ""


# ---------------------------------------------------------------------------
# Union type for content blocks
# ---------------------------------------------------------------------------

ContentBlock = Union[ProseBlock, Table, Figure, Equation, DefinitionBlock]


# ---------------------------------------------------------------------------
# Section (recursive tree)
# ---------------------------------------------------------------------------

class Section(BaseModel):
    section_id: str
    number: str = ""       # e.g. "2", "2.3", "10.2.1"
    title: str = ""
    level: int = 0         # depth in hierarchy (1 = chapter)
    page_start: int = 0
    page_end: int = 0
    parent_section_id: str = ""
    content_blocks: list[ContentBlock] = Field(default_factory=list)
    subsections: list[Section] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Canonical document — top level
# ---------------------------------------------------------------------------

class CanonicalDocument(BaseModel):
    metadata: DocumentMetadata
    sections: list[Section] = Field(default_factory=list)

    # -- Global queries (convenience) -------------------------------------

    def find_object_by_id(self, object_id: str) -> ContentBlock | TableRow | None:
        """Find any content block or table row by object_id across all sections."""
        for obj in self._iter_all_blocks():
            if obj.object_id == object_id:
                return obj
            if isinstance(obj, Table):
                for row in obj.rows:
                    if row.object_id == object_id:
                        return row
        return None

    def get_all_tables(self) -> list[Table]:
        return [b for b in self._iter_all_blocks() if isinstance(b, Table)]

    def get_all_rows(self) -> list[TableRow]:
        rows: list[TableRow] = []
        for t in self.get_all_tables():
            rows.extend(t.rows)
        return rows

    def get_all_figures(self) -> list[Figure]:
        return [b for b in self._iter_all_blocks() if isinstance(b, Figure)]

    def get_all_prose(self) -> list[ProseBlock]:
        return [b for b in self._iter_all_blocks() if isinstance(b, ProseBlock)]

    def get_all_equations(self) -> list[Equation]:
        return [b for b in self._iter_all_blocks() if isinstance(b, Equation)]

    def get_section_by_id(self, section_id: str) -> Section | None:
        for sec in self._iter_all_sections():
            if sec.section_id == section_id:
                return sec
        return None

    def get_section_by_number(self, number: str) -> Section | None:
        for sec in self._iter_all_sections():
            if sec.number == number:
                return sec
        return None

    # -- Internal iteration helpers ----------------------------------------

    def _iter_all_sections(self) -> list[Section]:
        result: list[Section] = []
        def _walk(sections: list[Section]) -> None:
            for s in sections:
                result.append(s)
                _walk(s.subsections)
        _walk(self.sections)
        return result

    def _iter_all_blocks(self) -> list[ContentBlock]:
        blocks: list[ContentBlock] = []
        for sec in self._iter_all_sections():
            blocks.extend(sec.content_blocks)
        return blocks


# ---------------------------------------------------------------------------
# Utility: compute hashes
# ---------------------------------------------------------------------------

def compute_sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()
