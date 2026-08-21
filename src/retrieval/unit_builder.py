"""
Retrieval-Unit Builder — Converts CanonicalDocument into domain-aware, structured Retrieval Units.

Supports generating two retrieval unit variants:
- Variant A (Standalone baseline): Standalone table rows, prose blocks, figures, and equations.
- Variant B (Composite Section Context): Enriches table rows and figures with local section introductory prose,
  preceding explanatory notes, and explicit domain qualifiers.

Consumes: data/canonical/TLE987x_6x_rev1.1.json
Outputs:
- data/retrieval/retrieval_units_variant_a.jsonl
- data/retrieval/retrieval_units_variant_b.jsonl
- data/retrieval/retrieval_units.jsonl (default symlink/copy of Variant B)
"""

import os
import sys
import json
from src.ingestion.canonical_schema import CanonicalDocument, Section, Table, Figure, Equation, DefinitionBlock, ProseBlock
from src.retrieval.retrieval_schema import RetrievalUnit, RetrievalUnitType


def infer_domain_from_section(section_number: str, section_title: str) -> str:
    """Infers hardware domain tagging from chapter/section number and title."""
    num_part = section_number.split('.')[0] if section_number else ""
    title_lower = section_title.lower()

    if num_part == "1" or "overview" in title_lower or "family" in title_lower:
        return "OVERVIEW"
    elif num_part == "2" or "pgu" in title_lower or "power supply" in title_lower or "vpre" in title_lower or "vddp" in title_lower or "vddc" in title_lower:
        return "PGU"
    elif num_part == "3" or "cgu" in title_lower or "clock" in title_lower or "crystal" in title_lower:
        return "CLOCK"
    elif num_part == "4" or "gpio" in title_lower or "pull-up" in title_lower:
        return "GPIO"
    elif num_part == "5" or "lin" in title_lower:
        return "LIN"
    elif num_part == "6" or "mon" in title_lower or "high-voltage monitor" in title_lower:
        return "MON"
    elif num_part == "7" or "adc1" in title_lower:
        return "ADC1"
    elif num_part == "8" or "sdadc" in title_lower or "adc3" in title_lower:
        return "SDADC"
    elif num_part == "9" or "bridge driver" in title_lower or "gate driver" in title_lower:
        return "BRIDGE_DRIVER"
    elif num_part == "10" or "charge pump" in title_lower:
        return "CHARGE_PUMP"
    elif num_part == "11" or "csa" in title_lower or "current sense" in title_lower or "shunt" in title_lower:
        return "CSA"
    elif num_part == "12" or "sensor" in title_lower:
        return "SENSOR"
    elif num_part == "13" or "swd" in title_lower or "serial wire" in title_lower:
        return "SWD"
    elif num_part == "14" or "unused pin" in title_lower:
        return "UNUSED_PINS"
    elif num_part == "15" or "layout" in title_lower or "pcb" in title_lower:
        return "LAYOUT"
    return "GENERAL"


def build_retrieval_units(
    canonical_path: str = "data/canonical/TLE987x_6x_rev1.1.json",
    output_dir: str = "data/retrieval",
) -> tuple[list[RetrievalUnit], list[RetrievalUnit]]:
    if not os.path.exists(canonical_path):
        raise FileNotFoundError(f"Canonical document not found at {canonical_path}")

    with open(canonical_path, "r", encoding="utf-8") as f:
        doc = CanonicalDocument.model_validate_json(f.read())

    doc_id = doc.metadata.document_id
    doc_ver = doc.metadata.document_version

    units_var_a: list[RetrievalUnit] = []
    units_var_b: list[RetrievalUnit] = []

    unit_counter_a = 1
    unit_counter_b = 1

    sections = doc._iter_all_sections()

    for sec in sections:
        domain = infer_domain_from_section(sec.number, sec.title)

        prose_accumulator: list[ProseBlock] = []

        # Find section intro text (first 2 paragraphs if available)
        sec_prose_blocks = [b for b in sec.content_blocks if isinstance(b, ProseBlock)]
        sec_intro_text = " ".join([p.raw_text.strip() for p in sec_prose_blocks[:2]])

        def flush_prose(acc: list[ProseBlock]):
            nonlocal unit_counter_a, unit_counter_b
            if not acc:
                return

            text_a = f"Section {sec.number} {sec.title}\n" + "\n".join([p.raw_text.strip() for p in acc])
            text_b = f"Domain: {domain} | Section {sec.number} {sec.title}\n" + "\n".join([p.raw_text.strip() for p in acc])

            src_ids = [p.object_id for p in acc]
            src_hashes = [p.traceability.object_source_hash for p in acc if p.traceability]
            bbox = acc[0].traceability.bbox if acc and acc[0].traceability else []

            u_a = RetrievalUnit(
                unit_id=f"RU_{unit_counter_a:04d}_prose_a",
                unit_type=RetrievalUnitType.section_prose,
                document_id=doc_id,
                document_version=doc_ver,
                section_id=sec.section_id,
                section_number=sec.number,
                section_title=sec.title,
                domain=domain,
                page_start=min(p.page for p in acc) if acc else sec.page_start,
                page_end=max(p.page for p in acc) if acc else sec.page_end,
                text_content=text_a,
                source_object_ids=src_ids,
                source_hashes=src_hashes,
                bbox=bbox,
            )
            unit_counter_a += 1
            units_var_a.append(u_a)

            u_b = RetrievalUnit(
                unit_id=f"RU_{unit_counter_b:04d}_prose_b",
                unit_type=RetrievalUnitType.section_prose,
                document_id=doc_id,
                document_version=doc_ver,
                section_id=sec.section_id,
                section_number=sec.number,
                section_title=sec.title,
                domain=domain,
                page_start=min(p.page for p in acc) if acc else sec.page_start,
                page_end=max(p.page for p in acc) if acc else sec.page_end,
                text_content=text_b,
                source_object_ids=src_ids,
                source_hashes=src_hashes,
                bbox=bbox,
            )
            unit_counter_b += 1
            units_var_b.append(u_b)

        for block in sec.content_blocks:
            if isinstance(block, ProseBlock):
                prose_accumulator.append(block)
                if len(prose_accumulator) >= 3:
                    flush_prose(prose_accumulator)
                    prose_accumulator = []

            elif isinstance(block, Table):
                flush_prose(prose_accumulator)
                prose_accumulator = []

                t_title = block.title or f"Table in Section {sec.number}"
                headers_str = " | ".join(block.headers_raw)
                rows_str = "\n".join([" | ".join(r.raw_cells.values()) for r in block.rows])
                bbox = block.traceability.bbox if block.traceability else []

                # Variant A: Standalone Table Summary
                t_summary_a = f"Section {sec.number} {sec.title}\n{t_title}\nHeaders: {headers_str}\n{rows_str}"
                # Variant B: Composite Section Context Table Summary
                t_summary_b = f"Domain: {domain} | Section {sec.number} {sec.title}\nOverview: {sec_intro_text[:250]}\n{t_title}\nHeaders: {headers_str}\n{rows_str}"

                units_var_a.append(
                    RetrievalUnit(
                        unit_id=f"RU_{unit_counter_a:04d}_tbl_summary_a",
                        unit_type=RetrievalUnitType.table_summary,
                        document_id=doc_id,
                        document_version=doc_ver,
                        section_id=sec.section_id,
                        section_number=sec.number,
                        section_title=sec.title,
                        domain=domain,
                        page_start=block.page,
                        page_end=block.page,
                        text_content=t_summary_a,
                        source_object_ids=[block.object_id],
                        source_hashes=[block.traceability.object_source_hash] if block.traceability else [],
                        bbox=bbox,
                    )
                )
                unit_counter_a += 1

                units_var_b.append(
                    RetrievalUnit(
                        unit_id=f"RU_{unit_counter_b:04d}_tbl_summary_b",
                        unit_type=RetrievalUnitType.table_summary,
                        document_id=doc_id,
                        document_version=doc_ver,
                        section_id=sec.section_id,
                        section_number=sec.number,
                        section_title=sec.title,
                        domain=domain,
                        page_start=block.page,
                        page_end=block.page,
                        text_content=t_summary_b,
                        source_object_ids=[block.object_id],
                        source_hashes=[block.traceability.object_source_hash] if block.traceability else [],
                        bbox=bbox,
                    )
                )
                unit_counter_b += 1

                # Table-Row Units
                for r_idx, row in enumerate(block.rows):
                    row_kv = ", ".join([f"{k}: {v}" for k, v in row.raw_cells.items() if v])
                    row_bbox = row.traceability.bbox if row.traceability else bbox

                    # Variant A: Standalone Row
                    row_text_a = f"Section {sec.number} {sec.title}\n{t_title}\nHeaders: {headers_str}\nRow {r_idx+1}: {row_kv}"
                    # Variant B: Composite Row with Section Intro Context
                    row_text_b = f"Domain: {domain} | Section {sec.number} {sec.title}\nContext: {sec_intro_text[:200]}\n{t_title}\nHeaders: {headers_str}\nRow {r_idx+1}: {row_kv}"

                    units_var_a.append(
                        RetrievalUnit(
                            unit_id=f"RU_{unit_counter_a:04d}_tbl_row_a",
                            unit_type=RetrievalUnitType.table_row,
                            document_id=doc_id,
                            document_version=doc_ver,
                            section_id=sec.section_id,
                            section_number=sec.number,
                            section_title=sec.title,
                            domain=domain,
                            page_start=row.traceability.page if row.traceability else block.page,
                            page_end=row.traceability.page if row.traceability else block.page,
                            text_content=row_text_a,
                            source_object_ids=[block.object_id, row.object_id],
                            source_hashes=[row.traceability.object_source_hash] if row.traceability else [],
                            bbox=row_bbox,
                        )
                    )
                    unit_counter_a += 1

                    units_var_b.append(
                        RetrievalUnit(
                            unit_id=f"RU_{unit_counter_b:04d}_tbl_row_b",
                            unit_type=RetrievalUnitType.table_row,
                            document_id=doc_id,
                            document_version=doc_ver,
                            section_id=sec.section_id,
                            section_number=sec.number,
                            section_title=sec.title,
                            domain=domain,
                            page_start=row.traceability.page if row.traceability else block.page,
                            page_end=row.traceability.page if row.traceability else block.page,
                            text_content=row_text_b,
                            source_object_ids=[block.object_id, row.object_id],
                            source_hashes=[row.traceability.object_source_hash] if row.traceability else [],
                            bbox=row_bbox,
                        )
                    )
                    unit_counter_b += 1

            elif isinstance(block, Figure):
                flush_prose(prose_accumulator)
                prose_accumulator = []
                bbox = block.traceability.bbox if block.traceability else []

                fig_text_a = f"Section {sec.number} {sec.title}\n{block.caption}\nContext: {block.nearby_text}\nImage: {block.image_path}"
                fig_text_b = f"Domain: {domain} | Section {sec.number} {sec.title}\nIntro: {sec_intro_text[:200]}\n{block.caption}\nContext: {block.nearby_text}\nImage: {block.image_path}"

                units_var_a.append(
                    RetrievalUnit(
                        unit_id=f"RU_{unit_counter_a:04d}_fig_a",
                        unit_type=RetrievalUnitType.figure_context,
                        document_id=doc_id,
                        document_version=doc_ver,
                        section_id=sec.section_id,
                        section_number=sec.number,
                        section_title=sec.title,
                        domain=domain,
                        page_start=block.page,
                        page_end=block.page,
                        text_content=fig_text_a,
                        source_object_ids=[block.object_id],
                        source_hashes=[block.traceability.object_source_hash] if block.traceability else [],
                        bbox=bbox,
                    )
                )
                unit_counter_a += 1

                units_var_b.append(
                    RetrievalUnit(
                        unit_id=f"RU_{unit_counter_b:04d}_fig_b",
                        unit_type=RetrievalUnitType.figure_context,
                        document_id=doc_id,
                        document_version=doc_ver,
                        section_id=sec.section_id,
                        section_number=sec.number,
                        section_title=sec.title,
                        domain=domain,
                        page_start=block.page,
                        page_end=block.page,
                        text_content=fig_text_b,
                        source_object_ids=[block.object_id],
                        source_hashes=[block.traceability.object_source_hash] if block.traceability else [],
                        bbox=bbox,
                    )
                )
                unit_counter_b += 1

            elif isinstance(block, Equation):
                flush_prose(prose_accumulator)
                prose_accumulator = []
                bbox = block.traceability.bbox if block.traceability else []

                eq_text_a = f"Section {sec.number} {sec.title}\nFormula: {block.raw_text}"
                eq_text_b = f"Domain: {domain} | Section {sec.number} {sec.title}\nFormula: {block.raw_text}"

                units_var_a.append(
                    RetrievalUnit(
                        unit_id=f"RU_{unit_counter_a:04d}_eq_a",
                        unit_type=RetrievalUnitType.equation_definition,
                        document_id=doc_id,
                        document_version=doc_ver,
                        section_id=sec.section_id,
                        section_number=sec.number,
                        section_title=sec.title,
                        domain=domain,
                        page_start=block.page,
                        page_end=block.page,
                        text_content=eq_text_a,
                        source_object_ids=[block.object_id],
                        source_hashes=[block.traceability.object_source_hash] if block.traceability else [],
                        bbox=bbox,
                    )
                )
                unit_counter_a += 1

                units_var_b.append(
                    RetrievalUnit(
                        unit_id=f"RU_{unit_counter_b:04d}_eq_b",
                        unit_type=RetrievalUnitType.equation_definition,
                        document_id=doc_id,
                        document_version=doc_ver,
                        section_id=sec.section_id,
                        section_number=sec.number,
                        section_title=sec.title,
                        domain=domain,
                        page_start=block.page,
                        page_end=block.page,
                        text_content=eq_text_b,
                        source_object_ids=[block.object_id],
                        source_hashes=[block.traceability.object_source_hash] if block.traceability else [],
                        bbox=bbox,
                    )
                )
                unit_counter_b += 1

        flush_prose(prose_accumulator)

    os.makedirs(output_dir, exist_ok=True)
    var_a_path = os.path.join(output_dir, "retrieval_units_variant_a.jsonl")
    var_b_path = os.path.join(output_dir, "retrieval_units_variant_b.jsonl")
    default_path = os.path.join(output_dir, "retrieval_units.jsonl")

    with open(var_a_path, "w", encoding="utf-8") as f:
        for u in units_var_a:
            f.write(u.model_dump_json() + "\n")

    with open(var_b_path, "w", encoding="utf-8") as f:
        for u in units_var_b:
            f.write(u.model_dump_json() + "\n")

    # Default retrieval_units.jsonl receives Variant B (composite context variant)
    with open(default_path, "w", encoding="utf-8") as f:
        for u in units_var_b:
            f.write(u.model_dump_json() + "\n")

    print(f"Generated Variant A ({len(units_var_a)} units) and Variant B ({len(units_var_b)} units) in {output_dir}")
    return units_var_a, units_var_b


if __name__ == "__main__":
    build_retrieval_units()
