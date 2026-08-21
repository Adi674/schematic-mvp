import re
import pymupdf
from src.ingestion.canonical_schema import Section


def parse_toc(doc: pymupdf.Document, document_id: str) -> list[Section]:
    """
    Parses section hierarchy from TOC pages or text line patterns.
    Returns list of top-level root Section objects with child subsections populated.
    """
    sections_flat: list[Section] = []

    # Parse from pages 1 and 2 (0-indexed: pages 2 and 3 of document)
    toc_text = ""
    for page_num in [1, 2]:
        if page_num < doc.page_count:
            page = doc[page_num]
            toc_text += page.get_text() + "\n"

    lines = [l.strip() for l in toc_text.splitlines() if l.strip()]
    i = 0
    while i < len(lines):
        line = lines[i]

        # Case 1: Two-line entry (Line N = number "1.1", Line N+1 = "Title ....... 4")
        m_num = re.match(r"^(\d+(?:\.\d+)*)$", line)
        if m_num and i + 1 < len(lines):
            sec_num = m_num.group(1)
            next_line = lines[i + 1]
            m_title = re.search(r"^(.*?)\.{2,}\s*(\d+)$", next_line)
            if m_title:
                title = m_title.group(1).strip()
                page_num = int(m_title.group(2))
                level = len(sec_num.split("."))

                section = Section(
                    section_id=f"{document_id}_sec_{sec_num.replace('.', '_')}",
                    number=sec_num,
                    title=title,
                    level=level,
                    page_start=page_num,
                )
                sections_flat.append(section)
                i += 2
                continue

        # Case 2: Single-line entry ("1.1 Title ....... 4")
        m_single = re.match(r"^(\d+(?:\.\d+)*)?\s*(.*?)\.{2,}\s*(\d+)$", line)
        if m_single and m_single.group(2):
            sec_num = m_single.group(1) or ""
            title = m_single.group(2).strip()
            page_num = int(m_single.group(3))
            if title not in ("About this document", "Table of contents", "Scope and purpose"):
                level = len(sec_num.split(".")) if sec_num else 1
                sec_id_suffix = sec_num.replace(".", "_") if sec_num else f"unnamed_{i}"
                section = Section(
                    section_id=f"{document_id}_sec_{sec_id_suffix}",
                    number=sec_num,
                    title=title,
                    level=level,
                    page_start=page_num,
                )
                sections_flat.append(section)

        i += 1

    # Fallback to regex scan of headings across full document if TOC failed
    if not sections_flat:
        for page_idx in range(doc.page_count):
            page_num = page_idx + 1
            page_text = doc[page_idx].get_text()
            for line in page_text.splitlines():
                m_hd = re.match(r"^(\d+(?:\.\d+)+)\s+([A-Z].*)$", line.strip())
                if m_hd:
                    sec_num = m_hd.group(1)
                    title = m_hd.group(2)
                    level = len(sec_num.split("."))
                    section = Section(
                        section_id=f"{document_id}_sec_{sec_num.replace('.', '_')}",
                        number=sec_num,
                        title=title,
                        level=level,
                        page_start=page_num,
                    )
                    sections_flat.append(section)

    # Correct page_end calculation:
    # For any section at level L, page_end is the page_start of the next section at level <= L minus 1
    for idx in range(len(sections_flat)):
        curr = sections_flat[idx]
        next_sibling_page = None
        for j in range(idx + 1, len(sections_flat)):
            if sections_flat[j].level <= curr.level:
                next_sibling_page = sections_flat[j].page_start
                break

        if next_sibling_page is not None:
            curr.page_end = max(curr.page_start, next_sibling_page - 1 if next_sibling_page > curr.page_start else curr.page_start)
        else:
            curr.page_end = doc.page_count

    # Build hierarchical section tree
    root_sections: list[Section] = []
    stack: list[Section] = []

    for sec in sections_flat:
        while stack and stack[-1].level >= sec.level:
            stack.pop()

        if stack:
            sec.parent_section_id = stack[-1].section_id
            stack[-1].subsections.append(sec)
        else:
            root_sections.append(sec)

        stack.append(sec)

    return root_sections
