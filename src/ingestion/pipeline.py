"""
Pipeline Orchestrator — Converts PDF into Canonical Document Model.

Integrates:
- TOC & Hierarchy Parser (toc_parser.py)
- Layout Parser & Text Block Extractor (layout_parser.py)
- Table Extractor with coordinate fallback (table_extractor.py)
- Figure & Schematic Extractor (figure_extractor.py)
- Equation & Definition Extractor (equation_extractor.py)

Outputs canonical JSON to data/canonical/{document_id}_{version}.json
"""

import os
import sys
import json
import pymupdf

from src.ingestion.canonical_schema import (
    CanonicalDocument,
    DocumentMetadata,
    Section,
    Table,
    Figure,
    Equation,
    DefinitionBlock,
    compute_sha256,
)
from src.ingestion.toc_parser import parse_toc
from src.ingestion.layout_parser import extract_page_blocks, assign_blocks_to_sections
from src.ingestion.table_extractor import extract_tables_from_page, extract_borderless_table
from src.ingestion.figure_extractor import extract_figures_from_page
from src.ingestion.equation_extractor import extract_equations_from_blocks


def run_ingestion_pipeline(
    pdf_path: str,
    document_id: str = "TLE987x_6x",
    document_version: str = "1.1",
    title: str = "TLE987x/6x Hardware design guideline",
    manufacturer: str = "Infineon Technologies AG",
    product_family: str = "MOTIX MCU",
    output_dir: str = "data/canonical",
    figures_dir: str = "data/figures",
) -> CanonicalDocument:
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found at {pdf_path}")

    # Compute PDF file hash
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    document_hash = compute_sha256(pdf_bytes)

    doc = pymupdf.open(pdf_path)
    page_count = len(doc)

    metadata = DocumentMetadata(
        document_id=document_id,
        document_version=document_version,
        title=title,
        manufacturer=manufacturer,
        product_family=product_family,
        date="2022-04-01",
        page_count=page_count,
        document_hash=document_hash,
    )

    # 1. Parse TOC hierarchy
    sections = parse_toc(doc, document_id)

    # 2. Extract page blocks & assign text prose to sections
    all_page_blocks = {}
    for page_idx in range(page_count):
        page_num = page_idx + 1
        page = doc[page_idx]
        blocks = extract_page_blocks(page, page_num)
        all_page_blocks[page_num] = blocks

    assign_blocks_to_sections(
        all_page_blocks, sections, document_id, document_version, document_hash
    )

    # Helper function to find section by page number
    def find_section_for_page(p_num: int) -> Section | None:
        def search(secs):
            for s in secs:
                if s.page_start <= p_num <= s.page_end:
                    sub = search(s.subsections)
                    return sub if sub else s
            return None
        return search(sections)

    # 3. Extract Tables, Figures, Equations per page & insert into sections
    for page_idx in range(page_count):
        page_num = page_idx + 1
        page = doc[page_idx]

        target_sec = find_section_for_page(page_num)
        if not target_sec:
            continue

        # Extract Tables
        tables = extract_tables_from_page(
            page, page_num, document_id, document_version, document_hash
        )
        
        # Check special borderless table fallback for Page 11 (Table 4) if missing
        if page_num == 11 and len(tables) < 2:
            t4_fallback = extract_borderless_table(
                page, page_num, (40.0, 95.0, 550.0, 295.0),
                document_id, document_version, document_hash
            )
            if t4_fallback:
                t4_fallback.title = "Table 4 Component selection for VS pin"
                t4_fallback.table_id = f"table_p11_t4"
                tables.insert(0, t4_fallback)

        for t in tables:
            t.page = page_num
            t.section_id = target_sec.section_id
            t.order = len(target_sec.content_blocks)
            target_sec.content_blocks.append(t)

        # Extract Figures
        figs = extract_figures_from_page(
            page, page_num, document_id, document_version, document_hash, figures_dir
        )
        for fig in figs:
            fig.page = page_num
            fig.section_id = target_sec.section_id
            fig.order = len(target_sec.content_blocks)
            target_sec.content_blocks.append(fig)

        # Extract Equations
        eqs, defs = extract_equations_from_blocks(
            all_page_blocks[page_num], page_num, target_sec.section_id,
            document_id, document_version, document_hash
        )
        for eq in eqs:
            eq.page = page_num
            eq.order = len(target_sec.content_blocks)
            target_sec.content_blocks.append(eq)
        for df in defs:
            df.page = page_num
            df.order = len(target_sec.content_blocks)
            target_sec.content_blocks.append(df)

    canonical_doc = CanonicalDocument(metadata=metadata, sections=sections)

    # 4. Save canonical JSON
    os.makedirs(output_dir, exist_ok=True)
    out_filename = f"{document_id}_rev{document_version}.json"
    out_path = os.path.join(output_dir, out_filename)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(canonical_doc.model_dump_json(indent=2))

    print(f"Ingestion complete: Canonical document written to {out_path}")
    return canonical_doc


if __name__ == "__main__":
    pdf_file = "TLE987x_6x Hardware design guideline.pdf"
    if len(sys.argv) > 1:
        pdf_file = sys.argv[1]
    run_ingestion_pipeline(pdf_file)
