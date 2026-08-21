"""
Embeddings Wrapper — Uses local sentence-transformers model (BAAI/bge-small-en-v1.5 or all-MiniLM-L6-v2)
for repeatable, deterministic, offline vector embedding.
"""

from typing import Optional
from sentence_transformers import SentenceTransformer


class LocalEmbeddings:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        try:
            self.model = SentenceTransformer(model_name)
        except Exception:
            # Fallback to all-MiniLM-L6-v2 if BAAI model is unavailable offline
            print(f"Fallback to all-MiniLM-L6-v2 embedding model...")
            self.model_name = "all-MiniLM-L6-v2"
            self.model = SentenceTransformer(self.model_name)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings = self.model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        # BGE query prefix if using BAAI
        if "bge" in self.model_name.lower():
            text = f"Represent this sentence for searching relevant passages: {query}"
        else:
            text = query
        embedding = self.model.encode(text, show_progress_bar=False, normalize_embeddings=True)
        return embedding.tolist()


_embedding_instance: Optional[LocalEmbeddings] = None


def get_embeddings(model_name: str = "BAAI/bge-small-en-v1.5") -> LocalEmbeddings:
    global _embedding_instance
    if _embedding_instance is None:
        _embedding_instance = LocalEmbeddings(model_name)
    return _embedding_instance
