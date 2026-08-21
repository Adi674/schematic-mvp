"""
Chroma Vector Database Ingestion Script.
Reads data/raw_doc/tle987x_full_pdf_text.txt, splits text by Chapter section headers (Chapters 1 to 15),
attaches metadata (chapter_num, chapter_name, domain, source_chunk_id), and embeds into Chroma DB.
"""

import os
import re
import json
import chromadb


def parse_and_ingest_pdf():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_text_path = os.path.join(base_dir, "data", "raw_doc", "tle987x_full_pdf_text.txt")
    chroma_db_dir = os.path.join(base_dir, "data", "chroma_db")

    if not os.path.exists(full_text_path):
        raise FileNotFoundError(f"Full text file not found at: {full_text_path}")

    with open(full_text_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split document by chapter sections (e.g. "## 1 TLE987x/6x family", "## 2 Power supply generation unit (PGU)")
    raw_sections = content.split("## ")

    domain_mapping = {
        1: ("OVERVIEW", "chunk_ch1_overview"),
        2: ("PGU", "chunk_ch2_table5"),
        3: ("CLOCK", "chunk_ch3_table8"),
        4: ("GPIO", "chunk_ch4_table10"),
        5: ("LIN", "chunk_ch5_lin"),
        6: ("MON", "chunk_ch6_table11"),
        7: ("ADC", "chunk_ch7_table13"),
        8: ("ADC", "chunk_ch8_table15"),
        9: ("BRIDGE_DRIVER", "chunk_ch9_table"),
        10: ("CHARGE_PUMP", "chunk_ch10_cp"),
        11: ("CSA", "chunk_ch11_csa"),
        12: ("SENSOR", "chunk_ch12_sensor"),
        13: ("SWD", "chunk_ch13_swd"),
        14: ("UNUSED_PINS", "chunk_ch14_table17"),
        15: ("LAYOUT", "chunk_ch15_layout")
    }

    documents = []
    metadatas = []
    ids = []

    seen_ids = set()

    for sec in raw_sections:
        sec = sec.strip()
        if not sec:
            continue

        match = re.match(r'^(\d+)\s+([^\n]+)', sec)
        if match:
            chapter_num = int(match.group(1))
            chapter_name = match.group(2)
        else:
            continue

        doc_id = f"doc_ch_{chapter_num}"
        if doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)

        domain, chunk_id = domain_mapping.get(chapter_num, ("GENERAL", f"chunk_ch{chapter_num}"))

        documents.append(f"## {sec}")
        metadatas.append({
            "chapter_num": chapter_num,
            "chapter_name": chapter_name,
            "domain": domain,
            "chunk_id": chunk_id,
            "source_doc": "TLE987x_HW_Guideline_Rev1.1"
        })
        ids.append(doc_id)

    print(f"Parsed {len(documents)} unique chapter documents from full PDF text.")

    # Initialize persistent Chroma DB client
    client = chromadb.PersistentClient(path=chroma_db_dir)

    # Get or create collection
    collection = client.get_or_create_collection(
        name="tle987x_guideline_chunks",
        metadata={"hnsw:space": "cosine"}
    )

    # Upsert documents into collection
    collection.upsert(
        documents=documents,
        metadatas=metadatas,
        ids=ids
    )

    print(f"Successfully ingested {len(documents)} complete chapter documents into Chroma DB at: {chroma_db_dir}")


if __name__ == "__main__":
    parse_and_ingest_pdf()
