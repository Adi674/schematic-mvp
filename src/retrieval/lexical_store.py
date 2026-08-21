"""
Lexical Store — BM25 index over retrieval units at data/indexes/lexical/.
Preserves exact symbol identifiers (CVDDP, VDDP, CVDDC, RMON, CVDH, ADC3.P, etc.).
"""

import os
import re
import json
import math
from typing import Optional
from src.retrieval.retrieval_schema import RetrievalUnit, QueryResult


def tokenize_symbol_aware(text: str) -> list[str]:
    """
    Tokenizer that preserves exact technical symbols, pin names, and component identifiers
    (e.g., CVDDP, C_VDDP, R_GATE, 10kOhm, 470nF, TLE9871QXA20).
    """
    # Lowercase text but extract exact symbol tokens
    text_clean = text.replace("-", "_")
    # Match words, symbols with numbers/underscores/dots
    tokens = re.findall(r'[a-zA-Z0-9_\.]+', text_clean.lower())
    return [t for t in tokens if len(t) > 1 or t.isdigit()]


class LexicalBM25Store:
    def __init__(self, index_dir: str = "data/indexes/lexical"):
        self.index_dir = index_dir
        self.units: list[RetrievalUnit] = []
        self.doc_tokens: list[list[str]] = []
        self.doc_freqs: list[dict[str, int]] = []
        self.df: dict[str, int] = {}
        self.avg_dl: float = 0.0
        self.k1: float = 1.5
        self.b: float = 0.75

    def build_index(self, units_path: str = "data/retrieval/retrieval_units.jsonl") -> int:
        if not os.path.exists(units_path):
            raise FileNotFoundError(f"Retrieval units not found at {units_path}")

        self.units = []
        self.doc_tokens = []
        self.doc_freqs = []
        self.df = {}
        total_len = 0

        with open(units_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    unit = RetrievalUnit.model_validate_json(line)
                    self.units.append(unit)
                    tokens = tokenize_symbol_aware(unit.text_content)
                    self.doc_tokens.append(tokens)
                    total_len += len(tokens)

                    freqs: dict[str, int] = {}
                    for t in tokens:
                        freqs[t] = freqs.get(t, 0) + 1
                    self.doc_freqs.append(freqs)

                    for t in set(tokens):
                        self.df[t] = self.df.get(t, 0) + 1

        N = len(self.units)
        self.avg_dl = total_len / N if N > 0 else 1.0

        # Save index metadata
        os.makedirs(self.index_dir, exist_ok=True)
        meta_path = os.path.join(self.index_dir, "bm25_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "doc_count": N,
                "avg_dl": self.avg_dl,
                "df": self.df,
            }, f, indent=2)

        print(f"Indexed {N} retrieval units in BM25 Lexical Store.")
        return N

    def search(
        self,
        query: str,
        top_k: int = 10,
        domain_filter: Optional[str] = None,
        unit_type_filter: Optional[str] = None,
    ) -> list[QueryResult]:
        if not self.units:
            # Try to build index if not loaded
            self.build_index()

        q_tokens = tokenize_symbol_aware(query)
        if not q_tokens:
            return []

        N = len(self.units)
        scores: list[tuple[float, int]] = []

        for idx, (unit, freqs, tokens) in enumerate(zip(self.units, self.doc_freqs, self.doc_tokens)):
            # Apply domain / unit_type metadata filtering if specified
            if domain_filter and unit.domain != domain_filter:
                continue
            if unit_type_filter and unit.unit_type.value != unit_type_filter:
                continue

            doc_len = len(tokens)
            score = 0.0

            for q_term in q_tokens:
                if q_term not in freqs:
                    continue
                tf = freqs[q_term]
                df = self.df.get(q_term, 0)
                # BM25 IDF formula
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
                num = tf * (self.k1 + 1.0)
                den = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avg_dl))
                score += idf * (num / den)

            if score > 0.0:
                scores.append((score, idx))

        scores.sort(key=lambda x: x[0], reverse=True)
        top_scores = scores[:top_k]

        results: list[QueryResult] = []
        for rank, (score, idx) in enumerate(top_scores, start=1):
            unit = self.units[idx]
            results.append(
                QueryResult(
                    unit_id=unit.unit_id,
                    score=score,
                    rank=rank,
                    retrieval_method="lexical",
                    unit=unit,
                )
            )

        return results


if __name__ == "__main__":
    bm25 = LexicalBM25Store()
    bm25.build_index()
