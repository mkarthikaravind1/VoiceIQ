"""
Ingest FAQ knowledge base into ChromaDB.
Run once: python -m app.rag.ingest
Re-run anytime knowledge_base.json is updated.
"""
import json
import os
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from app.config import get_settings

settings = get_settings()

FAQ_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "../../data/knowledge_base.json")
)

def ingest():
    print("📚 Starting FAQ ingestion into ChromaDB...")

    # Load FAQ data
    with open(FAQ_PATH) as f:
        faqs = json.load(f)

    # ChromaDB client (persistent)
    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)

    # Embedding function
    ef = SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model)

    # Delete existing collection to avoid duplicates on re-run
    try:
        client.delete_collection("faq")
        print("   Deleted existing 'faq' collection")
    except Exception:
        pass

    collection = client.create_collection(name="faq", embedding_function=ef) # type: ignore

    # Prepare documents
    # We embed "question + answer" so retrieval works on both question similarity
    # and answer content
    documents, metadatas, ids = [], [], []
    for faq in faqs:
        doc = f"Q: {faq['question']}\nA: {faq['answer']}"
        documents.append(doc)
        metadatas.append({"question": faq["question"], "answer": faq["answer"], "id": faq["id"]})
        ids.append(faq["id"])

    collection.add(documents=documents, metadatas=metadatas, ids=ids)
    print(f"✅ Ingested {len(faqs)} FAQs into ChromaDB at '{settings.chroma_persist_dir}'")


if __name__ == "__main__":
    ingest()