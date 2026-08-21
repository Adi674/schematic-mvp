import pymupdf
from typing import Optional

from src.ingestion.canonical_schema import (
    Table,
    TableRow,
    Traceability,
    ExtractionStatus,
    compute_sha256,
)

def normalize_text(text: str) -> str:
    """Normalize text by replacing special characters and fixing subscript artifacts."""
    if not text:
        return ""
    # Fix common subscript artifacts in this PDF
    text = text.replace("C\nVDDP", "CVDDP")
    text = text.replace("C\nVDDC", "CVDDC")
    text = text.replace("R\nGATE", "RGATE")
    
    # Replace unicode characters
    text = text.replace("µ", "u")
    text = text.replace("Ω", "Ohm")
    text = text.replace("≥", ">=")
    text = text.replace("≤", "<=")
    text = text.replace("…", "...")
    
    return text.strip()

def _find_table_title(page: pymupdf.Page, bbox: tuple[float, float, float, float]) -> str:
    """Try to find a table title/caption just above the table bbox."""
    x0, y0, x1, y1 = bbox
    blocks = page.get_text("blocks")
    title = ""
    min_dist = 50.0 # max distance to look above
    
    for b in blocks:
        bx0, by0, bx1, by1, btext, bblock_no, bblock_type = b
        if bblock_type != 0: # not text
            continue
        if by1 <= y0 + 10 and (y0 - by1) < min_dist:
            if "table" in btext.lower():
                title = btext.strip()
                min_dist = y0 - by1
    
    return title.replace("\n", " ")

def extract_tables_from_page(
    page: pymupdf.Page,
    page_num: int,
    document_id: str,
    document_version: str,
    document_hash: str,
) -> list[Table]:
    """Extract tables from a PDF page using PyMuPDF find_tables()."""
    tables = []
    found_tables = page.find_tables()
    
    for i, t in enumerate(found_tables):
        if not t.header or not t.extract():
            continue
            
        bbox = t.bbox
        title = _find_table_title(page, bbox)
        
        headers_raw = [str(h) if h is not None else "" for h in t.header.names]
        rows_data = t.extract()
        
        # Check if top row is actually table title/header
        if headers_raw and headers_raw[0].lower().startswith("table") and rows_data:
            if not title:
                title = " ".join([h for h in headers_raw if h]).strip()
            # Promote row 0 to be the real headers
            headers_raw = [str(cell) if cell is not None else "" for cell in rows_data[0]]
            rows_data = rows_data[1:]

        headers_normalized = [normalize_text(h) for h in headers_raw]
        
        table_rows = []
        for row_idx, row in enumerate(rows_data):
            raw_cells = {}
            normalized_cells = {}
            row_text = ""
            for col_idx, cell_val in enumerate(row):
                header_name = headers_normalized[col_idx] if col_idx < len(headers_normalized) else f"col_{col_idx}"
                if not header_name:
                    header_name = f"col_{col_idx}"
                    
                cell_str = str(cell_val) if cell_val is not None else ""
                raw_cells[header_name] = cell_str
                normalized_cells[header_name] = normalize_text(cell_str)
                row_text += cell_str + " | "
                
            row_obj_id = f"row_p{page_num}_{i}_{row_idx}"
            
            trace_row = Traceability(
                document_id=document_id,
                document_version=document_version,
                page=page_num,
                bbox=list(bbox),
                object_id=row_obj_id,
                parent_id=f"table_p{page_num}_{i}",
                source_text=row_text,
                object_source_hash=compute_sha256(row_text),
                document_hash=document_hash
            )
            
            table_row = TableRow(
                object_id=row_obj_id,
                table_id=f"table_p{page_num}_{i}",
                order=row_idx,
                raw_cells=raw_cells,
                normalized_cells=normalized_cells,
                traceability=trace_row,
                extraction_status=ExtractionStatus.validated,
                confidence=1.0
            )
            table_rows.append(table_row)
            
        if len(headers_raw) < 1 or len(table_rows) < 1:
            continue
            
        table_obj_id = f"table_p{page_num}_{i}"
        table_source_text = title + "\n" + " | ".join(headers_raw) + "\n" + "\n".join([" | ".join(r.raw_cells.values()) for r in table_rows])
        
        trace = Traceability(
            document_id=document_id,
            document_version=document_version,
            page=page_num,
            bbox=list(bbox),
            object_id=table_obj_id,
            source_text=table_source_text,
            object_source_hash=compute_sha256(table_source_text),
            document_hash=document_hash
        )
        
        table = Table(
            object_id=table_obj_id,
            table_id=table_obj_id,
            title=title,
            headers_raw=headers_raw,
            headers_normalized=headers_normalized,
            rows=table_rows,
            traceability=trace,
            extraction_status=ExtractionStatus.validated,
            confidence=0.9
        )
        tables.append(table)
        
    return tables

def extract_borderless_table(
    page: pymupdf.Page,
    page_num: int,
    bbox_hint: tuple[float, float, float, float],
    document_id: str,
    document_version: str,
    document_hash: str,
) -> Optional[Table]:
    """Fallback to extract a borderless table using coordinate alignment."""
    x0_hint, y0_hint, x1_hint, y1_hint = bbox_hint
    words = page.get_text("words", clip=bbox_hint)
    
    if not words:
        return None
        
    lines = []
    current_line = []
    current_y = None
    y_tolerance = 3.0
    
    words.sort(key=lambda w: (w[3], w[0]))
    
    for w in words:
        x0, y0, x1, y1, text, block_no, line_no, word_no = w
        if current_y is None:
            current_y = y1
            current_line.append(w)
        elif abs(y1 - current_y) <= y_tolerance:
            current_line.append(w)
            current_y = max(current_y, y1)
        else:
            current_line.sort(key=lambda w: w[0])
            lines.append(current_line)
            current_line = [w]
            current_y = y1
            
    if current_line:
        current_line.sort(key=lambda w: w[0])
        lines.append(current_line)
        
    if len(lines) < 2:
        return None
        
    headers = []
    col_x_ranges = []
    
    for i, w in enumerate(lines[0]):
        headers.append(w[4])
        if i < len(lines[0]) - 1:
            col_x_ranges.append((w[0] - 5, lines[0][i+1][0] - 1))
        else:
            col_x_ranges.append((w[0] - 5, x1_hint))
            
    headers_normalized = [normalize_text(h) for h in headers]
    
    rows = []
    for row_idx, line in enumerate(lines[1:]):
        raw_cells = {h: "" for h in headers_normalized}
        
        for w in line:
            x0, y0, x1, y1, text, _, _, _ = w
            assigned_col = -1
            for col_idx, (cx0, cx1) in enumerate(col_x_ranges):
                if cx0 <= x0 <= cx1 or cx0 <= x1 <= cx1 or (x0 <= cx0 and x1 >= cx1):
                    assigned_col = col_idx
                    break
                    
            if assigned_col != -1 and assigned_col < len(headers_normalized):
                h_norm = headers_normalized[assigned_col]
                if raw_cells[h_norm]:
                    raw_cells[h_norm] += " " + text
                else:
                    raw_cells[h_norm] = text
                    
        normalized_cells = {k: normalize_text(v) for k, v in raw_cells.items()}
        
        row_text = " | ".join(raw_cells.values())
        row_obj_id = f"row_p{page_num}_fallback_{row_idx}"
        table_id = f"table_p{page_num}_fallback"
        
        trace_row = Traceability(
            document_id=document_id,
            document_version=document_version,
            page=page_num,
            bbox=list(bbox_hint),
            object_id=row_obj_id,
            parent_id=table_id,
            source_text=row_text,
            object_source_hash=compute_sha256(row_text),
            document_hash=document_hash
        )
        
        row = TableRow(
            object_id=row_obj_id,
            table_id=table_id,
            order=row_idx,
            raw_cells=raw_cells,
            normalized_cells=normalized_cells,
            traceability=trace_row,
            extraction_status=ExtractionStatus.needs_review,
            confidence=0.5
        )
        rows.append(row)
        
    table_id = f"table_p{page_num}_fallback"
    table_source_text = " | ".join(headers) + "\n" + "\n".join([" | ".join(r.raw_cells.values()) for r in rows])
    
    trace_table = Traceability(
        document_id=document_id,
        document_version=document_version,
        page=page_num,
        bbox=list(bbox_hint),
        object_id=table_id,
        source_text=table_source_text,
        object_source_hash=compute_sha256(table_source_text),
        document_hash=document_hash
    )
    
    table = Table(
        object_id=table_id,
        table_id=table_id,
        title="Fallback Extracted Table",
        headers_raw=headers,
        headers_normalized=headers_normalized,
        rows=rows,
        traceability=trace_table,
        extraction_status=ExtractionStatus.needs_review,
        confidence=0.5
    )
    
    return table
