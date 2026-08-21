import re
import uuid

from src.ingestion.canonical_schema import Equation, DefinitionBlock, Traceability, ExtractionStatus, compute_sha256

def extract_equations_from_blocks(
    text_blocks: list[dict],
    page_num: int,
    section_id: str,
    document_id: str,
    document_version: str,
    document_hash: str,
) -> tuple[list[Equation], list[DefinitionBlock]]:
    equations = []
    definitions = []
    
    math_chars = set('+-*/=≤≥<>')
    
    for i, block in enumerate(text_blocks):
        raw_text = block.get('raw_text', '')
        bbox = block.get('bbox', [])
        
        if '=' in raw_text:
            if any(op in raw_text for op in math_chars) and len(raw_text.split()) < 20:
                eq_id = f"eq_{uuid.uuid4().hex[:8]}"
                
                normalized_text = raw_text.replace('\n', ' ').strip()
                
                traceability = Traceability(
                    document_id=document_id,
                    document_version=document_version,
                    page=page_num,
                    bbox=bbox,
                    object_id=eq_id,
                    source_text=raw_text,
                    object_source_hash=compute_sha256(raw_text),
                    document_hash=document_hash
                )
                
                eq = Equation(
                    object_id=eq_id,
                    section_id=section_id,
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                    traceability=traceability
                )
                equations.append(eq)
                
                def_texts = []
                for j in range(max(0, i-2), min(len(text_blocks), i+3)):
                    if j != i:
                        adj_text = text_blocks[j].get('raw_text', '').strip()
                        if 'where' in adj_text.lower() or ' is the ' in adj_text or '=' in adj_text:
                            def_texts.append((j, text_blocks[j]))
                
                for j, def_block in def_texts:
                    def_raw = def_block.get('raw_text', '')
                    def_id = f"def_{uuid.uuid4().hex[:8]}"
                    
                    def_trace = Traceability(
                        document_id=document_id,
                        document_version=document_version,
                        page=page_num,
                        bbox=def_block.get('bbox', []),
                        object_id=def_id,
                        source_text=def_raw,
                        object_source_hash=compute_sha256(def_raw),
                        document_hash=document_hash
                    )
                    
                    defn = DefinitionBlock(
                        object_id=def_id,
                        section_id=section_id,
                        raw_text=def_raw,
                        normalized_text=def_raw.replace('\n', ' ').strip(),
                        traceability=def_trace
                    )
                    definitions.append(defn)
                    
    return equations, definitions
