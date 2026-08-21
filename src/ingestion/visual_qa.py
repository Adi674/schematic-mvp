"""
Visual QA Suite — Generates high-res visual crops of extracted tables/figures
and builds an interactive side-by-side HTML verification report.
"""

import os
import sys
import json
import pymupdf

from src.ingestion.canonical_schema import CanonicalDocument


def generate_visual_qa(
    canonical_path: str = "data/canonical/TLE987x_6x_rev1.1.json",
    pdf_path: str = "TLE987x_6x Hardware design guideline.pdf",
    output_dir: str = "ingestion_qa",
) -> str:
    if not os.path.exists(canonical_path):
        raise FileNotFoundError(f"Canonical document not found at {canonical_path}")
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found at {pdf_path}")

    os.makedirs(output_dir, exist_ok=True)

    with open(canonical_path, "r", encoding="utf-8") as f:
        doc = CanonicalDocument.model_validate_json(f.read())

    pdf_doc = pymupdf.open(pdf_path)

    tables = doc.get_all_tables()
    figures = doc.get_all_figures()

    report_items = []

    # 1. Render Table Crops & Build Report Data
    for idx, table in enumerate(tables):
        page_num = table.page
        page = pdf_doc[page_num - 1]

        crop_rel_path = f"crop_table_p{page_num}_{idx}.png"
        crop_abs_path = os.path.join(output_dir, crop_rel_path)

        bbox = table.traceability.bbox if table.traceability else [40, 100, 550, 400]
        # Pad bbox slightly for context
        padded_bbox = [
            max(0, bbox[0] - 10),
            max(0, bbox[1] - 10),
            min(page.rect.width, bbox[2] + 10),
            min(page.rect.height, bbox[3] + 10),
        ]
        rect = pymupdf.Rect(padded_bbox)
        pix = page.get_pixmap(clip=rect, dpi=180)
        pix.save(crop_abs_path)

        rows_json = [r.raw_cells for r in table.rows]

        report_items.append({
            "type": "Table",
            "title": table.title or f"Table (Page {page_num})",
            "page": page_num,
            "crop_img": crop_rel_path,
            "status": table.extraction_status.value.upper(),
            "confidence": f"{table.confidence * 100:.0f}%",
            "headers": table.headers_normalized,
            "rows": rows_json,
        })

    # 2. Render Figure Crops
    for idx, figure in enumerate(figures):
        page_num = figure.page
        crop_rel_path = f"crop_fig_p{page_num}_{idx}.png"
        crop_abs_path = os.path.join(output_dir, crop_rel_path)

        if os.path.exists(figure.image_path):
            # Copy or re-render
            page = pdf_doc[page_num - 1]
            bbox = figure.traceability.bbox if figure.traceability else [0, 0, page.rect.width, 400]
            rect = pymupdf.Rect(bbox)
            pix = page.get_pixmap(clip=rect, dpi=180)
            pix.save(crop_abs_path)
        else:
            crop_rel_path = ""

        report_items.append({
            "type": "Figure",
            "title": figure.caption or f"Figure (Page {page_num})",
            "page": page_num,
            "crop_img": crop_rel_path,
            "status": figure.extraction_status.value.upper(),
            "confidence": f"{figure.confidence * 100:.0f}%",
            "headers": [],
            "rows": [{"Caption": figure.caption, "Nearby Context": figure.nearby_text[:200]}],
        })

    # 3. Generate HTML Deck
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Ingestion Visual QA Report — {doc.metadata.document_id}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f4f6f9; margin: 0; padding: 20px; color: #333; }}
        h1 {{ color: #1a252f; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        .meta-bar {{ background: #fff; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 20px; }}
        .card {{ background: #fff; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); margin-bottom: 25px; overflow: hidden; display: flex; flex-direction: row; }}
        .card-left {{ flex: 1; padding: 15px; border-right: 1px solid #eee; background: #fafafa; text-align: center; }}
        .card-left img {{ max-width: 100%; border: 1px solid #ddd; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .card-right {{ flex: 1; padding: 20px; overflow-x: auto; }}
        .badge {{ padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.85em; color: #fff; }}
        .badge-pass {{ background: #2ecc71; }}
        .badge-review {{ background: #f39c12; }}
        table.parsed-table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.9em; }}
        table.parsed-table th, table.parsed-table td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        table.parsed-table th {{ background: #f2f4f7; }}
    </style>
</head>
<body>
    <h1>Ingestion Visual QA Report</h1>
    <div class="meta-bar">
        <strong>Document:</strong> {doc.metadata.title} ({doc.metadata.document_id} Rev {doc.metadata.document_version}) |
        <strong>Pages:</strong> {doc.metadata.page_count} |
        <strong>Hash:</strong> <code>{doc.metadata.document_hash[:16]}...</code>
    </div>
"""

    for item in report_items:
        badge_cls = "badge-pass" if item["status"] in ("PASS", "VALIDATED") else "badge-review"
        html_content += f"""
    <div class="card">
        <div class="card-left">
            <h3>Original PDF Crop (Page {item['page']})</h3>
            <img src="{item['crop_img']}" alt="PDF Crop" />
        </div>
        <div class="card-right">
            <h3>{item['type']}: {item['title']}</h3>
            <p>
                <span class="badge {badge_cls}">{item['status']}</span>
                <strong>Confidence:</strong> {item['confidence']} |
                <strong>Page:</strong> {item['page']}
            </p>
            <h4>Parsed Structured Content:</h4>
            <table class="parsed-table">
"""
        if item["headers"]:
            html_content += "<tr>" + "".join([f"<th>{h}</th>" for h in item["headers"]]) + "</tr>"

        for row in item["rows"]:
            html_content += "<tr>"
            for k, v in row.items():
                html_content += f"<td><strong>{k}:</strong> {v}</td>"
            html_content += "</tr>"

        html_content += """
            </table>
        </div>
    </div>
"""

    html_content += """
</body>
</html>
"""

    report_path = os.path.join(output_dir, "report.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Visual QA Report generated at {report_path}")
    return report_path


if __name__ == "__main__":
    canonical_file = "data/canonical/TLE987x_6x_rev1.1.json"
    if len(sys.argv) > 1:
        canonical_file = sys.argv[1]
    generate_visual_qa(canonical_file)
