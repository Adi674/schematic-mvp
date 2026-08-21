"""
Hybrid Retriever — Combines Dense Vector Search (Chroma) and Lexical Search (BM25)
using Reciprocal Rank Fusion (RRF).

Strictly no LLM reranker, no API calls, no Composer node. Pure evidence retrieval.
"""

from typing import Optional
from src.retrieval.retrieval_schema import RetrievalUnit, QueryResult
from src.retrieval.vector_store import DenseVectorStore
from src.retrieval.lexical_store import LexicalBM25Store


class HybridRetriever:
    def __init__(
        self,
        dense_store: Optional[DenseVectorStore] = None,
        lexical_store: Optional[LexicalBM25Store] = None,
        rrf_k: int = 60,
    ):
        self.dense_store = dense_store or DenseVectorStore()
        self.lexical_store = lexical_store or LexicalBM25Store()
        self.rrf_k = rrf_k

    def search(
        self,
        query: str,
        top_k: int = 10,
        dense_top_k: int = 20,
        lexical_top_k: int = 20,
        domain_filter: Optional[str] = None,
        unit_type_filter: Optional[str] = None,
        method: str = "hybrid",  # "hybrid", "dense_only", "lexical_only"
    ) -> list[QueryResult]:
        if method == "dense_only":
            return self.dense_store.search(
                query, top_k=top_k, domain_filter=domain_filter, unit_type_filter=unit_type_filter
            )
        elif method == "lexical_only":
            return self.lexical_store.search(
                query, top_k=top_k, domain_filter=domain_filter, unit_type_filter=unit_type_filter
            )

        # Hybrid RRF fusion
        dense_results = self.dense_store.search(
            query, top_k=dense_top_k, domain_filter=domain_filter, unit_type_filter=unit_type_filter
        )
        lexical_results = self.lexical_store.search(
            query, top_k=lexical_top_k, domain_filter=domain_filter, unit_type_filter=unit_type_filter
        )

        rrf_scores: dict[str, float] = {}
        units_map: dict[str, RetrievalUnit] = {}

        # Accumulate RRF score from Dense results
        for res in dense_results:
            u_id = res.unit_id
            rrf_scores[u_id] = rrf_scores.get(u_id, 0.0) + (1.0 / (self.rrf_k + res.rank))
            units_map[u_id] = res.unit

        # Accumulate RRF score from Lexical results
        for res in lexical_results:
            u_id = res.unit_id
            rrf_scores[u_id] = rrf_scores.get(u_id, 0.0) + (1.0 / (self.rrf_k + res.rank))
            if u_id not in units_map:
                units_map[u_id] = res.unit

        # Sort by composite RRF score
        sorted_units = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        hybrid_results: list[QueryResult] = []
        for rank, (u_id, score) in enumerate(sorted_units, start=1):
            hybrid_results.append(
                QueryResult(
                    unit_id=u_id,
                    score=score,
                    rank=rank,
                    retrieval_method="hybrid_rrf",
                    unit=units_map[u_id],
                )
            )

        return hybrid_results
