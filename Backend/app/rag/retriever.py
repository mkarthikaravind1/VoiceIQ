"""
RAG retriever — queries ChromaDB for top-K relevant FAQ entries.
Used by the agent's search_faq tool.
"""
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from app.config import get_settings
from typing import Any, cast

settings = get_settings()


class FAQRetriever:
    def __init__(self):
        self.collection = None
        self._load()

    def _load(self):
        print("🔍 Loading ChromaDB FAQ collection...")
        client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        ef = SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model)
        try:
            self.collection = client.get_collection(name="faq", embedding_function=cast(Any, ef))
            print(f"✅ ChromaDB ready ({self.collection.count()} FAQs loaded)")
        except Exception:
            print("⚠️  ChromaDB 'faq' collection not found. Run: python -m app.rag.ingest")
            self.collection = None

    def retrieve(self, query: str) -> str:
        """Context string for the LLM, or "" if nothing is close enough."""
        return self.search(query)[0]

    def search(self, query: str) -> tuple[str, float | None, list[str]]:
        """
        Query ChromaDB for top-K relevant FAQ entries.
        Returns (context, best_distance, ids). Context is "" when nothing is
        close enough to the question; best_distance lets the caller tell a
        strong match from a weak one.
        """
        if self.collection is None or self.collection.count() == 0:
            return "", None, []

        results = self.collection.query(
            query_texts=[query],
            n_results=min(settings.rag_top_k, self.collection.count()),
        )

        metadatas = results.get("metadatas")
        if not metadatas or not metadatas[0]:
            return "", None, []

        distances = results.get("distances")

        # Keep only entries that are actually related to the question, so an
        # off-topic question gets empty context instead of three random FAQs.
        context_parts, ids = [], []
        for i, meta in enumerate(metadatas[0]):
            distance = distances[0][i] if distances else None
            if distance is not None and distance > settings.rag_max_distance:
                continue
            context_parts.append(f"Q: {meta['question']}\nA: {meta['answer']}")
            ids.append(str(meta.get("id", "")))

        best = min(distances[0]) if distances and distances[0] else None
        return "\n\n".join(context_parts), best, ids


# Singleton
_retriever: FAQRetriever | None = None


def get_retriever() -> FAQRetriever:
    global _retriever
    if _retriever is None:
        _retriever = FAQRetriever()
    return _retriever
