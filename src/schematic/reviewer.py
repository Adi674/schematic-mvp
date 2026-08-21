"""
Reviewer Orchestrator Module.
Thin stateful service connecting Extractor, SectionIdentifier, ChecklistEngine, and ReferenceVerifier.
"""

import uuid
from typing import Dict, Any, Optional, List
from src.schematic.schema import (
    SchematicFacts,
    ParseCropResponse,
    ReviewCropResponse,
    CheckResultState,
    FindingItem
)
from src.schematic.extractor import SchematicExtractor
from src.schematic.section_identifier import SectionIdentifier
from src.schematic.checklist import ChecklistEngine
from src.schematic.reference_verifier import ReferenceVerifier
from src.schematic.semantic_extractor import SemanticSchematicExtractor


class SchematicReviewService:
    """Thin orchestrator for two-stage crop review flow."""

    # def __init__(
    #     self,
    #     extractor: Optional[SchematicExtractor] = None,
    #     identifier: Optional[SectionIdentifier] = None,
    #     checklist_engine: Optional[ChecklistEngine] = None,
    #     verifier: Optional[ReferenceVerifier] = None
    # ):
    #     self.extractor = extractor or SchematicExtractor()
    #     self.identifier = identifier or SectionIdentifier()
    #     self.checklist_engine = checklist_engine or ChecklistEngine()
    #     self.verifier = verifier or ReferenceVerifier()
    #     self._reviews: Dict[str, Dict[str, Any]] = {}

    def __init__(
        self,
        semantic_extractor=None,
        extractor=None,
        identifier=None,
        checklist_engine=None,
        verifier=None
    ):
        self.semantic_extractor = (
            semantic_extractor or SemanticSchematicExtractor()
        )

        self.extractor = extractor
        self.identifier = identifier
        self.checklist_engine = checklist_engine
        self.verifier = verifier

        self._reviews = {}

    # def parse_crop(
    #     self,
    #     image_bytes: bytes,
    #     filename: str = "crop.png",
    #     width: int = 800,
    #     height: int = 600,
    #     device_hint: Optional[str] = None,
    #     mime_type: str = "image/png"
    # ) -> ParseCropResponse:
    #     """Stage 1: Extract schematic facts and generate candidate sections."""
    #     review_id = str(uuid.uuid4())

    #     facts: SchematicFacts = self.extractor.extract(
    #         image_bytes=image_bytes,
    #         image_id=filename,
    #         width=width,
    #         height=height,
    #         device_hint=device_hint,
    #         mime_type=mime_type
    #     )

    #     candidates = self.identifier.identify_sections(facts)
    #     needs_conf, suggested = self.identifier.determine_confirmation_needed(candidates)

    #     self._reviews[review_id] = {
    #         "facts": facts,
    #         "candidates": candidates,
    #         "filename": filename
    #     }

    #     return ParseCropResponse(
    #         review_id=review_id,
    #         extraction=facts,
    #         section_candidates=candidates,
    #         needs_confirmation=needs_conf,
    #         suggested_section=suggested
    #     )

    def parse_crop(
        self,
        image_bytes: bytes,
        filename: str = "crop.png",
        width: int = 800,
        height: int = 600,
        device_hint: Optional[str] = None,
        mime_type: str = "image/png"
    ):
        review_id = str(uuid.uuid4())

        semantic = self.semantic_extractor.extract(
            image_bytes=image_bytes,
            image_id=filename,
            width=width,
            height=height,
            mime_type=mime_type,
            device_hint=device_hint,
        )

        self._reviews[review_id] = {
            "semantic": semantic,
            "filename": filename,
        }

        return {
            "review_id": review_id,
            "extraction": semantic,
            "model": self.semantic_extractor.model_name,
        }

    def review_crop(
        self,
        review_id: str,
        selected_section: str
    ) -> ReviewCropResponse:
        """Stage 2: Run extraction quality checks + R5 reference comparison."""
        if review_id not in self._reviews:
            raise KeyError(f"Review session '{review_id}' not found.")

        facts: SchematicFacts = self._reviews[review_id]["facts"]

        # Extraction quality checks (E1-E5, R0)
        findings: List[FindingItem] = self.checklist_engine.evaluate_framework(
            facts=facts,
            selected_section=selected_section
        )

        # R5: Reference comparison (NEEDS_REVIEW default, never PASS by default)
        r5_finding = self.verifier.verify_section_requirements(
            facts=facts,
            selected_section=selected_section
        )
        findings.append(r5_finding)

        # Summary status
        summary_status = CheckResultState.PASS
        statuses = [f.status for f in findings]
        if CheckResultState.FAIL in statuses:
            summary_status = CheckResultState.FAIL
        elif CheckResultState.INSUFFICIENT_INPUT in statuses:
            summary_status = CheckResultState.INSUFFICIENT_INPUT
        elif CheckResultState.NEEDS_REVIEW in statuses or CheckResultState.WARNING in statuses:
            summary_status = CheckResultState.NEEDS_REVIEW

        return ReviewCropResponse(
            review_id=review_id,
            selected_section=selected_section,
            findings=findings,
            summary_status=summary_status
        )
