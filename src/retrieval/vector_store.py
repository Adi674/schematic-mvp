"""
Dense Vector Store — Persistent Chroma DB collection at data/indexes/vector/.
Stores embeddings and rich metadata for metadata filtering.
"""

import os
import json
import chromadb
from typing import Optional
from src.retrieval.retrieval_schema import RetrievalUnit, QueryResult
from src.retrieval.embeddings import get_embeddings


class DenseVectorStore:
    def __init__(
        self,
        persist_dir: str = "data/indexes/vector",
        collection_name: str = "schematic_retrieval_units",
    ):
        os.makedirs(persist_dir, exist_ok=True)
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        self.embeddings = get_embeddings()

    def build_index(self, units_path: str = "data/retrieval/retrieval_units.jsonl", batch_size: int = 100) -> int:
        if not os.path.exists(units_path):
            raise FileNotFoundError(f"Retrieval units not found at {units_path}")

        units: list[RetrievalUnit] = []
        with open(units_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    units.append(RetrievalUnit.model_validate_json(line))

        if not units:
            return 0

        existing_count = self.collection.count()
        if existing_count > 0:
            print(f"Resetting existing Chroma collection ({existing_count} items)...")
            self.client.delete_collection(self.collection.name)
            self.collection = self.client.create_collection(
                name=self.collection.name,
                metadata={"hnsw:space": "cosine"}
            )

        print(f"Indexing {len(units)} retrieval units into Chroma DB...")

        for i in range(0, len(units), batch_size):
            batch = units[i : i + batch_size]
            ids = [u.unit_id for u in batch]
            documents = [u.text_content for u in batch]
            metadatas = [
                {
                    "unit_id": u.unit_id,
                    "unit_type": u.unit_type.value,
                    "document_id": u.document_id,
                    "document_version": u.document_version,
                    "section_number": u.section_number,
                    "section_title": u.section_title,
                    "domain": u.domain,
                    "page_start": u.page_start,
                    "page_end": u.page_end,
                    "bbox_str": json.dumps(u.bbox),
                    "source_object_ids_str": json.dumps(u.source_object_ids),
                    "source_hashes_str": json.dumps(u.source_hashes),
                }
                for u in batch
            ]
            embeddings_list = self.embeddings.embed_texts(documents)

            self.collection.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings_list,
                metadatas=metadatas,
            )

        total_indexed = self.collection.count()
        print(f"Successfully indexed {total_indexed} retrieval units into Chroma DB collection '{self.collection.name}'.")
        return total_indexed

    def search(
        self,
        query: str,
        top_k: int = 10,
        domain_filter: Optional[str] = None,
        unit_type_filter: Optional[str] = None,
    ) -> list[QueryResult]:
        query_vec = self.embeddings.embed_query(query)

        where_clause = {}
        if domain_filter and unit_type_filter:
            where_clause = {"$and": [{"domain": domain_filter}, {"unit_type": unit_type_filter}]}
        elif domain_filter:
            where_clause = {"domain": domain_filter}
        elif unit_type_filter:
            where_clause = {"unit_type": unit_type_filter}

        kwargs = {
            "query_embeddings": [query_vec],
            "n_results": top_k,
        }
        if where_clause:
            kwargs["where"] = where_clause

        res = self.collection.query(**kwargs)

        results: list[QueryResult] = []
        if res and res["ids"] and res["ids"][0]:
            ids = res["ids"][0]
            distances = res["distances"][0] if res["distances"] else [0.0] * len(ids)
            documents = res["documents"][0] if res["documents"] else [""] * len(ids)
            metadatas = res["metadatas"][0] if res["metadatas"] else [{}] * len(ids)

            for rank, (u_id, dist, doc_str, meta) in enumerate(zip(ids, distances, documents, metadatas), start=1):
                score = max(0.0, 1.0 - dist)
                bbox = json.loads(meta.get("bbox_str", "[]"))
                src_ids = json.loads(meta.get("source_object_ids_str", "[]"))
                src_hashes = json.loads(meta.get("source_hashes_str", "[]"))

                unit = RetrievalUnit(
                    unit_id=u_id,
                    unit_type=meta.get("unit_type", "section_prose"),
                    document_id=meta.get("document_id", "TLE987x_6x"),
                    document_version=meta.get("document_version", "1.1"),
                    section_id=f"sec_{meta.get('section_number', '')}",
                    section_number=meta.get("section_number", ""),
                    section_title=meta.get("section_title", ""),
                    domain=meta.get("domain", "GENERAL"),
                    page_start=meta.get("page_start", 0),
                    page_end=meta.get("page_end", 0),
                    text_content=doc_str,
                    source_object_ids=src_ids,
                    source_hashes=src_hashes,
                    bbox=bbox,
                )
                results.append(
                    QueryResult(
                        unit_id=u_id,
                        score=score,
                        rank=rank,
                        retrieval_method="dense",
                        unit=unit,
                        bbox=bbox,
                        source_object_ids=src_ids,
                        object_source_hash=src_hashes[0] if src_hashes else "",
                        document_hash=meta.get("document_id", ""),
                    )
                )

        return results


if __name__ == "__main__":
    store = DenseVectorStore()
    store.build_index()
