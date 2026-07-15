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
            self.collection = client.get_collection(name="faq", embedding_function=cast(Any,ef)) 
            print(f"✅ ChromaDB ready ({self.collection.count()} FAQs loaded)")
        except Exception:
            print("⚠️  ChromaDB 'faq' collection not found. Run: python -m app.rag.ingest")
            self.collection = None

    def retrieve(self, query: str) -> str:
        """
        Query ChromaDB for top-K relevant FAQ entries.
        Returns a formatted context string for the LLM.
        """
        if self.collection is None or self.collection.count() == 0:
            return ""

        results = self.collection.query(
            query_texts=[query],
            n_results=min(settings.rag_top_k, self.collection.count()),
        )

        if not results["metadatas"] or results.get("metadatas") is None or not results["metadatas"]:
            return ""

        # Format retrieved entries as readable context
        context_parts = []
        for i, meta in enumerate(results["metadatas"][0]):
            distance = results["distances"][0][i] if results.get("distances") else None # type: ignore
            relevance = f" (relevance: {1 - distance:.2f})" if distance is not None else ""
            context_parts.append(f"Q: {meta['question']}\nA: {meta['answer']}{relevance}")

        return "\n\n".join(context_parts)


# Singleton
_retriever: FAQRetriever | None = None


def get_retriever() -> FAQRetriever:
    global _retriever
    if _retriever is None:
        _retriever = FAQRetriever()
    return _retriever