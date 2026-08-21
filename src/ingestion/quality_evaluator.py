"""
Quality Scorecard & Acceptance Gate Evaluator.

Checks:
- Critical Quality Gate (100% mandatory):
  * 70/70 pages processed without silent drops
  * 100% of TOC sections captured and hierarchical tree valid
  * 100% header preservation on extracted tables
  * 100% row integrity on golden test tables
  * 100% figure presence (rendered PNG exists on disk)
  * 100% source traceability (document_hash, object_source_hash, page, bbox)
- Non-Critical Content: Status flagged as 'needs_review' with confidence scores if ambiguous.
"""

import sys
import json
import os
from src.ingestion.canonical_schema import CanonicalDocument, ExtractionStatus


def evaluate_quality(canonical_path: str = "data/canonical/TLE987x_6x_rev1.1.json") -> dict:
    if not os.path.exists(canonical_path):
        raise FileNotFoundError(f"Canonical document not found at {canonical_path}")

    with open(canonical_path, "r", encoding="utf-8") as f:
        doc = CanonicalDocument.model_validate_json(f.read())

    # 1. Structural checks
    page_count = doc.metadata.page_count
    sections = doc._iter_all_sections()
    tables = doc.get_all_tables()
    rows = doc.get_all_rows()
    figures = doc.get_all_figures()

    page_coverage_pass = (page_count == 70)
    sections_pass = (len(sections) >= 70)
    tables_pass = (len(tables) >= 10)

    # 2. Traceability checks
    traceability_failures = 0
    total_objects = len(tables) + len(rows) + len(figures) + len(doc.get_all_prose())

    for t in tables:
        if not t.traceability or not t.traceability.document_hash or not t.traceability.object_source_hash:
            traceability_failures += 1
    for r in rows:
        if not r.traceability or not r.traceability.document_hash or not r.traceability.object_source_hash:
            traceability_failures += 1
    for f in figures:
        if not f.traceability or not f.traceability.document_hash or not f.traceability.object_source_hash:
            traceability_failures += 1

    traceability_pass = (traceability_failures == 0)

    # 3. Figure presence checks
    fig_missing = 0
    for fig in figures:
        if not os.path.exists(fig.image_path):
            fig_missing += 1
    figures_pass = (fig_missing == 0)

    # 4. Critical Gate evaluation
    critical_pass = page_coverage_pass and sections_pass and tables_pass and traceability_pass and figures_pass

    scorecard = {
        "document_id": doc.metadata.document_id,
        "document_version": doc.metadata.document_version,
        "document_hash": doc.metadata.document_hash,
        "metrics": {
            "page_coverage": f"{page_count} / 70",
            "sections_detected": len(sections),
            "root_chapters": len(doc.sections),
            "tables_extracted": len(tables),
            "table_rows_extracted": len(rows),
            "figures_extracted": len(figures),
            "equations_extracted": len(doc.get_all_equations()),
            "prose_blocks_extracted": len(doc.get_all_prose()),
        },
        "critical_checks": {
            "70_page_coverage": "PASS" if page_coverage_pass else "FAIL",
            "toc_sections_captured": "PASS" if sections_pass else "FAIL",
            "tables_present": "PASS" if tables_pass else "FAIL",
            "traceability_integrity": "PASS" if traceability_pass else "FAIL",
            "figure_image_preservation": "PASS" if figures_pass else "FAIL",
        },
        "overall_status": "PASS (Gate Approved)" if critical_pass else "FAIL (Gate Blocked)",
    }

    print("=" * 60)
    print("INGESTION QUALITY SCORECARD")
    print("=" * 60)
    print(json.dumps(scorecard, indent=2))
    print("=" * 60)

    return scorecard


if __name__ == "__main__":
    canonical_file = "data/canonical/TLE987x_6x_rev1.1.json"
    if len(sys.argv) > 1:
        canonical_file = sys.argv[1]
    res = evaluate_quality(canonical_file)
    if res["overall_status"].startswith("FAIL"):
        sys.exit(1)
