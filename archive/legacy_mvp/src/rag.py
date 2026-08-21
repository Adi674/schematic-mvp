"""
RAG Store Module (Chroma DB Integration).
Manages Chroma vector database, document chunks, domain metadata filtering,
direct get_chunk_by_id lookup (Chroma-first, chunks.json fallback),
and keyword-based fallback search.
"""

import os
import json
from typing import List, Dict, Any, Optional
import chromadb


def _get_chroma_collection():
    """Returns the Chroma collection if available, else None."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    chroma_dir = os.path.join(base_dir, "data", "chroma_db")
    if not os.path.exists(chroma_dir):
        return None
    try:
        client = chromadb.PersistentClient(path=chroma_dir)
        return client.get_collection("tle987x_guideline_chunks")
    except Exception:
        return None


def load_doc_chunks() -> List[Dict[str, Any]]:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    chunks_path = os.path.join(base_dir, "data", "raw_doc", "chunks.json")
    if not os.path.exists(chunks_path):
        return []

    with open(chunks_path, 'r', encoding='utf-8') as f:
        return json.load(f)


DOC_CHUNKS = load_doc_chunks()
CHUNK_LOOKUP = {c["chunk_id"]: c for c in DOC_CHUNKS}


def get_chunk_by_id(chunk_id: str) -> Optional[Dict[str, Any]]:
    """
    Direct lookup of document chunk by source_chunk_id.
    First queries Chroma DB (actual PDF text), falls back to chunks.json summaries.
    Used by Composer node when rule_engine produces a verdict linked to a source_chunk_id.
    """
    print(f"\n[RAG DIRECT LOOKUP] Querying chunk_id: '{chunk_id}'")

    # Try Chroma first — returns actual PDF-extracted text
    collection = _get_chroma_collection()
    if collection:
        try:
            results = collection.get(
                where={"chunk_id": chunk_id},
                include=["documents", "metadatas"],
                limit=3
            )
            if results and results.get("documents") and len(results["documents"]) > 0:
                # Combine multiple sub-chunks with same chunk_id into one
                combined_text = "\n\n".join(results["documents"])
                meta = results["metadatas"][0] if results["metadatas"] else {}
                print(f"[RAG DIRECT LOOKUP SUCCESS] Found in Chroma DB (Chapter {meta.get('chapter_num')}: {meta.get('chapter_name')})")
                print(f"  Excerpt: {combined_text[:120].replace(chr(10), ' ')}...")
                return {
                    "chunk_id": chunk_id,
                    "chapter_num": meta.get("chapter_num", 0),
                    "chapter_name": meta.get("chapter_name", ""),
                    "domain": meta.get("domain", ""),
                    "title": f"Chapter {meta.get('chapter_num', '?')}: {meta.get('chapter_name', '')}",
                    "text": combined_text
                }
        except Exception as e:
            print(f"[RAG DIRECT LOOKUP WARNING] Chroma query failed ({e}), falling back to chunks.json")

    # Fallback to hand-written chunks.json summaries
    res = CHUNK_LOOKUP.get(chunk_id)
    if res:
        print(f"[RAG DIRECT LOOKUP] Found in chunks.json fallback: {res.get('title')}")
    else:
        print(f"[RAG DIRECT LOOKUP] Chunk '{chunk_id}' not found in any store.")
    return res


def search_doc_chunks(query: str, domain: Optional[str] = None, top_k: int = 3) -> List[Dict[str, Any]]:
    """
    Performs Chroma Vector Search with Domain Metadata Filtering.
    Falls back to structured keyword search if Chroma DB collection is initializing.
    """
    print(f"\n{'='*30} [VECTOR RETRIEVAL] {'='*30}")
    print(f"Search Query: \"{query}\"")
    print(f"Domain Filter: {domain or 'None (Global Search)'} | Top-K: {top_k}")

    collection = _get_chroma_collection()
    if collection:
        try:
            where_clause = None
            if domain:
                where_clause = {"domain": domain.upper().strip()}

            results = collection.query(
                query_texts=[query],
                n_results=top_k,
                where=where_clause
            )

            retrieved = []
            if results and results.get("documents"):
                for docs, metas in zip(results["documents"], results["metadatas"]):
                    for d, m in zip(docs, metas):
                        retrieved.append({
                            "chunk_id": m.get("chunk_id", ""),
                            "chapter_num": m.get("chapter_num", 1),
                            "chapter_name": m.get("chapter_name", ""),
                            "domain": m.get("domain", ""),
                            "title": f"Chapter {m.get('chapter_num')}: {m.get('chapter_name')}",
                            "text": d
                        })
            if retrieved:
                print(f"[VECTOR RETRIEVAL SUCCESS] Retrieved {len(retrieved)} chunk(s) from Chroma DB:")
                for i, r in enumerate(retrieved, 1):
                    preview = r['text'][:120].replace('\n', ' ')
                    print(f"  {i}. [{r['chunk_id']}] (Chapter {r['chapter_num']}: {r['chapter_name']}, Domain: {r['domain']})")
                    print(f"     Preview: {preview}...")
                print(f"{'='*75}\n")
                return retrieved
        except Exception as e:
            print(f"[VECTOR RETRIEVAL WARNING] Chroma query error: {e}. Using keyword fallback.")

    # Fallback keyword match
    print("[VECTOR RETRIEVAL] Using keyword match fallback...")
    query_tokens = set(query.lower().split())
    filtered_chunks = DOC_CHUNKS
    if domain:
        domain_clean = domain.upper().strip()
        filtered_chunks = [c for c in DOC_CHUNKS if c.get("domain", "").upper() == domain_clean]
        if not filtered_chunks:
            filtered_chunks = DOC_CHUNKS

    scored_chunks = []
    for c in filtered_chunks:
        text_tokens = set(c["text"].lower().split())
        title_tokens = set(c["title"].lower().split())
        overlap = len(query_tokens.intersection(text_tokens)) + len(query_tokens.intersection(title_tokens)) * 2
        scored_chunks.append((overlap, c))

    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    fallback_res = [chunk for score, chunk in scored_chunks[:top_k]]
    print(f"[VECTOR RETRIEVAL FALLBACK] Retrieved {len(fallback_res)} chunk(s): {[c['chunk_id'] for c in fallback_res]}\n{'='*75}\n")
    return fallback_res

