import os
import re
import uuid
import pymupdf

from src.ingestion.canonical_schema import Figure, Traceability, ExtractionStatus, compute_sha256

def extract_figures_from_page(
    page: pymupdf.Page,
    page_num: int,
    document_id: str,
    document_version: str,
    document_hash: str,
    output_dir: str,
) -> list[Figure]:
    figures = []
    
    caption_pattern = re.compile(r'Figure\s+(\d+)\s*\n?(.+)', re.IGNORECASE)
    text_blocks = page.get_text("blocks")
    
    os.makedirs(output_dir, exist_ok=True)
    
    for i, block in enumerate(text_blocks):
        text = block[4].strip()
        match = caption_pattern.search(text)
        
        if match:
            fig_num = match.group(1)
            fig_slug = re.sub(r'[^a-zA-Z0-9]+', '_', match.group(2)[:20]).strip('_').lower()
            
            caption_bbox = block[:4]
            
            drawings = page.get_drawings()
            images = page.get_images()
            
            figure_bbox = None
            extraction_status = ExtractionStatus.needs_review
            
            min_x, min_y, max_x, max_y = 9999, 9999, 0, 0
            found_drawings = False
            
            for img in images:
                try:
                    img_bbox = page.get_image_bbox(img[0])
                    if img_bbox.y1 <= caption_bbox[1] + 10:
                        min_x = min(min_x, img_bbox.x0)
                        min_y = min(min_y, img_bbox.y0)
                        max_x = max(max_x, img_bbox.x1)
                        max_y = max(max_y, img_bbox.y1)
                        found_drawings = True
                except:
                    pass
            
            for path in drawings:
                rect = path["rect"]
                if rect.y1 <= caption_bbox[1] + 10:
                    min_x = min(min_x, rect.x0)
                    min_y = min(min_y, rect.y0)
                    max_x = max(max_x, rect.x1)
                    max_y = max(max_y, rect.y1)
                    found_drawings = True
            
            if found_drawings and min_x < max_x and min_y < max_y:
                figure_bbox = (min_x, min_y, max_x, max_y)
                extraction_status = ExtractionStatus.validated
            else:
                top_y = 0
                for j in range(i - 1, -1, -1):
                    if text_blocks[j][1] < caption_bbox[1]:
                        top_y = text_blocks[j][3]
                        break
                if top_y < caption_bbox[1]:
                    figure_bbox = (0, top_y, page.rect.width, caption_bbox[1])
                else:
                    figure_bbox = (0, 0, page.rect.width, caption_bbox[1])
                extraction_status = ExtractionStatus.needs_review
            
            figure_bbox_rect = pymupdf.Rect(figure_bbox)
            
            pix = page.get_pixmap(clip=figure_bbox_rect, dpi=200)
            img_filename = f"fig_{fig_num}_{fig_slug}.png"
            img_path = os.path.join(output_dir, img_filename)
            pix.save(img_path)
            
            nearby_texts = []
            if i > 0:
                nearby_texts.append(text_blocks[i-1][4].strip())
            if i < len(text_blocks) - 1:
                nearby_texts.append(text_blocks[i+1][4].strip())
            
            nearby_text = "\n".join(nearby_texts)
            
            figure_id = f"fig_{uuid.uuid4().hex[:8]}"
            source_text = text
            
            traceability = Traceability(
                document_id=document_id,
                document_version=document_version,
                page=page_num,
                bbox=list(caption_bbox),
                object_id=figure_id,
                source_text=source_text,
                object_source_hash=compute_sha256(source_text),
                document_hash=document_hash
            )
            
            fig = Figure(
                object_id=figure_id,
                figure_id=f"fig_{fig_num}",
                caption=text,
                image_path=img_path,
                nearby_text=nearby_text,
                traceability=traceability,
                extraction_status=extraction_status
            )
            figures.append(fig)

    return figures
