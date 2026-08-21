import re
import pymupdf
import hashlib
from src.ingestion.canonical_schema import Section, ProseBlock, Traceability


def is_header_footer(text: str, bbox: list[float], page_height: float) -> bool:
    """Detects running headers/footers by pattern and position."""
    text_clean = text.strip()
    y0, y1 = bbox[1], bbox[3]

    # Top ~90px or bottom ~50px
    is_top = y0 < 90
    is_bottom = y1 > (page_height - 65)

    if not (is_top or is_bottom):
        return False

    header_keywords = [
        "application note",
        "rev. 1.1",
        "2022-04-01",
        "tle987x/6x",
        "hardware design guideline",
    ]

    text_lower = text_clean.lower()
    lines = [l.strip().lower() for l in text_clean.splitlines() if l.strip()]

    # If it's a bottom block containing just page numbers or header keywords
    if is_bottom:
        if all(l.isdigit() or any(kw in l for kw in header_keywords) for l in lines):
            return True

    # If it's a top block containing running header lines
    if is_top:
        if all(l.isdigit() or any(kw in l for kw in header_keywords) for l in lines):
            return True

    return False


def normalize_text(raw: str) -> str:
    """Normalizes unicode characters."""
    replacements = {
        'µ': 'u',
        'Ω': 'Ohm',
        '≥': '>=',
        '≤': '<=',
        '±': '+/-',
        '°': ' deg',
        '–': '-', 
        '—': '-', 
        '‘': "'",
        '’': "'",
        '“': '"',
        '”': '"'
    }
    normalized = raw
    for k, v in replacements.items():
        normalized = normalized.replace(k, v)
    return normalized


def extract_page_blocks(page: pymupdf.Page, page_num: int) -> list[dict]:
    """Extracts text blocks with bbox, filters out header/footer patterns."""
    blocks = page.get_text("blocks")
    page_height = page.rect.height

    extracted = []

    for b in blocks:
        x0, y0, x1, y1, text, block_no, block_type = b

        if block_type == 0:
            b_type = 'text'
        elif block_type == 1:
            b_type = 'image'
        else:
            b_type = 'other'

        bbox = [x0, y0, x1, y1]

        if b_type == 'text':
            if is_header_footer(text, bbox, page_height):
                continue

        extracted.append({
            'page': page_num,
            'bbox': bbox,
            'raw_text': text,
            'block_type': b_type,
            'block_index': block_no
        })

    return extracted


def assign_blocks_to_sections(
    all_page_blocks: dict[int, list[dict]],
    sections: list[Section],
    document_id: str = "TLE987x_6x",
    document_version: str = "1.1",
    document_hash: str = "",
) -> None:
    """Assigns text blocks to their section based on page ranges."""
    def flatten_sections(secs):
        flat = []
        for s in secs:
            flat.append(s)
            flat.extend(flatten_sections(s.subsections))
        return flat

    flat_sections = flatten_sections(sections)
    if not flat_sections:
        return

    doc_id = document_id

    for page_num, blocks in all_page_blocks.items():
        candidates = [s for s in flat_sections if s.page_start <= page_num <= s.page_end]

        for block in blocks:
            best_section = None
            if candidates:
                best_section = max(candidates, key=lambda s: s.level)

            if best_section and block['block_type'] == 'text':
                raw_text = block['raw_text']
                obj_id = f"{doc_id}_p{page_num}_b{block['block_index']}"

                pb = ProseBlock(
                    object_id=obj_id,
                    section_id=best_section.section_id,
                    order=len(best_section.content_blocks),
                    page=page_num,
                    raw_text=raw_text,
                    normalized_text=normalize_text(raw_text),
                    traceability=Traceability(
                        document_id=doc_id,
                        document_version=document_version,
                        page=page_num,
                        bbox=block['bbox'],
                        object_id=obj_id,
                        parent_id=best_section.section_id,
                        source_text=raw_text,
                        object_source_hash=hashlib.sha256(raw_text.encode('utf-8')).hexdigest(),
                        document_hash=document_hash,
                    )
                )
                best_section.content_blocks.append(pb)
