"""
RAG retriever — queries ChromaDB for top-K relevant FAQ entries.
Used by the LangGraph faq_retrieve node.
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
        """
        Query ChromaDB for top-K relevant FAQ entries.
        Returns a formatted context string for the LLM, or "" if nothing is
        close enough to the question.
        """
        if self.collection is None or self.collection.count() == 0:
            return ""

        results = self.collection.query(
            query_texts=[query],
            n_results=min(settings.rag_top_k, self.collection.count()),
        )

        metadatas = results.get("metadatas")
        if not metadatas or not metadatas[0]:
            return ""

        distances = results.get("distances")

        # Keep only entries that are actually related to the question, so an
        # off-topic question gets empty context instead of three random FAQs.
        context_parts = []
        for i, meta in enumerate(metadatas[0]):
            distance = distances[0][i] if distances else None
            if distance is not None and distance > settings.rag_max_distance:
                continue
            context_parts.append(f"Q: {meta['question']}\nA: {meta['answer']}")

        return "\n\n".join(context_parts)


# Singleton
_retriever: FAQRetriever | None = None


def get_retriever() -> FAQRetriever:
    global _retriever
    if _retriever is None:
        _retriever = FAQRetriever()
    return _retriever
