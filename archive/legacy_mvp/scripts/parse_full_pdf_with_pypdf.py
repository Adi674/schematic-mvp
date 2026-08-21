"""
Full PDF Parsing and Ingestion Script using PyMuPDF and RecursiveCharacterTextSplitter.
Reads the actual 70-page 'TLE987x_6x Hardware design guideline.pdf', extracts text page-by-page,
splits text recursively, attaches sub-section chunk_ids that match source_chunk_id in rules_source.json,
and embeds into persistent Chroma DB.
"""

import os
import fitz  # PyMuPDF
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter


def get_page_chunks(page_num: int):
    """
    Maps each PDF page to one or more (chapter_num, chapter_name, domain, chunk_id) tuples.
    A page can produce MULTIPLE chunk_id assignments when it contains content
    from more than one sub-section (e.g. page 11 has Table 4 and VAREF text).

    Page ranges derived from Table of Contents (Pages 2-3) and verified against PDF.
    All 18 source_chunk_ids from rules_source.json are covered.
    """
    # ── Chapter 1: Overview ────────────────────────────────────────────────────
    if 1 <= page_num <= 8:
        return [(1, "TLE987x/6x family", "OVERVIEW", "chunk_ch1_overview")]

    # ── Chapter 2: PGU ─────────────────────────────────────────────────────────
    # Pages 9-10: VS pre-regulator intro + VPRE current budget text
    elif page_num in (9, 10):
        return [(2, "Power supply generation unit (PGU)", "PGU", "chunk_ch2_vpre")]

    # Page 11: Table 4 (VS pin), VAREF text, VPRE current budget table
    elif page_num == 11:
        return [
            (2, "Power supply generation unit (PGU)", "PGU", "chunk_ch2_table4"),
            (2, "Power supply generation unit (PGU)", "PGU", "chunk_ch2_varef"),
            (2, "Power supply generation unit (PGU)", "PGU", "chunk_ch2_vpre"),
        ]

    # Page 12: Table 5 (VDDP) + Table 6 (VDDC)
    elif page_num == 12:
        return [
            (2, "Power supply generation unit (PGU)", "PGU", "chunk_ch2_table5"),
            (2, "Power supply generation unit (PGU)", "PGU", "chunk_ch2_table6"),
        ]

    # Page 13: Table 7 (VDDEXT)
    elif page_num == 13:
        return [(2, "Power supply generation unit (PGU)", "PGU", "chunk_ch2_table7")]

    # ── Chapter 3: CGU ─────────────────────────────────────────────────────────
    elif 14 <= page_num <= 17:
        return [(3, "Clock generation unit (CGU)", "CLOCK", "chunk_ch3_table8")]

    # ── Chapter 4: GPIO ────────────────────────────────────────────────────────
    elif 18 <= page_num <= 20:
        return [(4, "General purpose inputs outputs (GPIO)", "GPIO", "chunk_ch4_table10")]

    # ── Chapter 5: LIN ─────────────────────────────────────────────────────────
    elif page_num == 21:
        return [(5, "LIN transceiver", "LIN", "chunk_ch5_lin")]

    # ── Chapter 6: MON ─────────────────────────────────────────────────────────
    elif page_num == 22:
        return [(6, "High-voltage monitor input (MON)", "MON", "chunk_ch6_table11")]

    # ── Chapter 7: ADC1 ────────────────────────────────────────────────────────
    elif 23 <= page_num <= 25:
        return [(7, "Analog to digital converters (ADC1)", "ADC", "chunk_ch7_table13")]

    # ── Chapter 8: SDADC ───────────────────────────────────────────────────────
    elif 26 <= page_num <= 28:
        return [(8, "Sigma-delta analog digital converters (ADC3/4)", "ADC", "chunk_ch8_table15")]

    # ── Chapter 9: Bridge Driver ───────────────────────────────────────────────
    # Pages 29-30: external component tables (R_GATE, R_GS, C_EMCPx, R_VDH, C_VDH, R_SH)
    elif page_num in (29, 30):
        return [(9, "Bridge driver (excluding charge pump)", "BRIDGE_DRIVER", "chunk_ch9_table")]

    # Page 31: gate capacitor ratio constraint (C_GD/C_GS <= 0.1)
    elif page_num == 31:
        return [
            (9, "Bridge driver (excluding charge pump)", "BRIDGE_DRIVER", "chunk_ch9_table"),
            (9, "Bridge driver (excluding charge pump)", "BRIDGE_DRIVER", "chunk_ch9_gate_ratio"),
        ]

    # Page 32: remaining bridge driver content
    elif page_num == 32:
        return [(9, "Bridge driver (excluding charge pump)", "BRIDGE_DRIVER", "chunk_ch9_gate_ratio")]

    # ── Chapter 10: Charge Pump ────────────────────────────────────────────────
    elif 33 <= page_num <= 42:
        return [(10, "Charge pump", "CHARGE_PUMP", "chunk_ch10_cp")]

    # ── Chapter 11: CSA ────────────────────────────────────────────────────────
    elif 43 <= page_num <= 54:
        return [(11, "Current sense amplifier", "CSA", "chunk_ch11_csa")]

    # ── Chapter 12: Sensor interfaces ─────────────────────────────────────────
    elif 55 <= page_num <= 56:
        return [(12, "Sensor interfaces", "SENSOR", "chunk_ch12_sensor")]

    # ── Chapter 13: SWD ────────────────────────────────────────────────────────
    elif 57 <= page_num <= 58:
        return [(13, "SWD (serial wire debug) interface circuitry", "SWD", "chunk_ch13_swd")]

    # ── Chapter 14: Unused Pins ────────────────────────────────────────────────
    elif page_num == 59:
        return [(14, "Unused pins", "UNUSED_PINS", "chunk_ch14_table17")]

    # ── Chapter 15: Layout ─────────────────────────────────────────────────────
    elif 60 <= page_num <= 68:
        return [(15, "Layout guidelines", "LAYOUT", "chunk_ch15_layout")]

    else:
        return [(15, "Revision history & Disclaimer", "LAYOUT", "chunk_ch15_layout")]


def parse_and_ingest_pdf():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdf_path = os.path.join(base_dir, "TLE987x_6x Hardware design guideline.pdf")
    chroma_db_dir = os.path.join(base_dir, "data", "chroma_db")

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found at: {pdf_path}")

    # 1. Open PDF using PyMuPDF for exact page-by-page text extraction
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    print(f"Opened '{pdf_path}' successfully. Total pages: {total_pages}")

    # Initialize LangChain RecursiveCharacterTextSplitter
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=900,
        chunk_overlap=150,
        separators=["\n\n", "\n", " ", ""]
    )

    all_documents = []
    all_metadatas = []
    all_ids = []

    global_chunk_idx = 0
    seen_unique_ids = set()

    for page_idx in range(total_pages):
        page_num = page_idx + 1
        page = doc.load_page(page_idx)
        page_text = page.get_text("text").strip()

        if not page_text:
            continue

        # Get one or more chunk_id assignments for this page
        page_chunk_assignments = get_page_chunks(page_num)

        # Split page text recursively
        page_chunks = text_splitter.split_text(page_text)

        for chunk_seq, chunk_text in enumerate(page_chunks):
            global_chunk_idx += 1

            # For multi-assignment pages, emit one record per chunk_id assignment
            for chap_num, chap_name, domain, chunk_id in page_chunk_assignments:
                unique_id = f"doc_p{page_num}_c{chunk_seq + 1}_{chunk_id}"

                # Avoid exact duplicates (same page+seq+chunk_id)
                if unique_id in seen_unique_ids:
                    continue
                seen_unique_ids.add(unique_id)

                all_documents.append(chunk_text)
                all_metadatas.append({
                    "page_num": page_num,
                    "chapter_num": chap_num,
                    "chapter_name": chap_name,
                    "domain": domain,
                    "chunk_id": chunk_id,
                    "source_doc": "TLE987x_6x Hardware design guideline.pdf"
                })
                all_ids.append(unique_id)

    print(f"Total split chunks created across all {total_pages} pages: {len(all_documents)}")

    # Verify all required chunk_ids are present
    present_chunk_ids = set(m["chunk_id"] for m in all_metadatas)
    required_chunk_ids = {
        "chunk_ch1_overview", "chunk_ch2_vpre", "chunk_ch2_table4", "chunk_ch2_table5",
        "chunk_ch2_table6", "chunk_ch2_table7", "chunk_ch2_varef", "chunk_ch3_table8",
        "chunk_ch4_table10", "chunk_ch5_lin", "chunk_ch6_table11", "chunk_ch7_table13",
        "chunk_ch8_table15", "chunk_ch9_table", "chunk_ch9_gate_ratio", "chunk_ch10_cp",
        "chunk_ch11_csa", "chunk_ch13_swd", "chunk_ch14_table17"
    }
    missing = required_chunk_ids - present_chunk_ids
    if missing:
        print(f"WARNING: Missing required chunk_ids: {missing}")
    else:
        print(f"All {len(required_chunk_ids)} required chunk_ids are present in ingestion batch.")

    # 2. Ingest into persistent Chroma DB
    client = chromadb.PersistentClient(path=chroma_db_dir)

    # Recreate collection to ensure clean ingestion
    try:
        client.delete_collection("tle987x_guideline_chunks")
        print("Deleted existing 'tle987x_guideline_chunks' collection.")
    except Exception:
        pass

    collection = client.create_collection(
        name="tle987x_guideline_chunks",
        metadata={"hnsw:space": "cosine"}
    )

    # Insert in batches of 100 to avoid batch payload limits
    batch_size = 100
    for i in range(0, len(all_documents), batch_size):
        end = i + batch_size
        collection.upsert(
            documents=all_documents[i:end],
            metadatas=all_metadatas[i:end],
            ids=all_ids[i:end]
        )
        print(f"  Ingested batch {i // batch_size + 1}: records {i+1}–{min(end, len(all_documents))}")

    print(f"\nSuccessfully ingested {len(all_documents)} chunks into Chroma DB at: {chroma_db_dir}")
    print(f"Unique chunk_ids in DB: {sorted(present_chunk_ids)}")


if __name__ == "__main__":
    parse_and_ingest_pdf()
