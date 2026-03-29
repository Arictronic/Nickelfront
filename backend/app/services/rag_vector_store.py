"""RAG vector store service based on Chroma + LangChain."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_community.vectorstores import Chroma

from app.core.config import settings
from app.services.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)


class RAGVectorStore:
    def __init__(self, persist_directory: str | None = None):
        self.persist_directory = persist_directory or str(Path(settings.CHROMA_DB_PATH) / "rag")
        self._vector_store: Chroma | None = None
        self._client: chromadb.Client | None = None
        self._collection_name = "rag_documents"
        logger.info("RAGVectorStore init: %s", self.persist_directory)

    def _init_client(self) -> chromadb.Client:
        if self._client is None:
            self._client = chromadb.Client(
                ChromaSettings(
                    persist_directory=self.persist_directory,
                    is_persistent=True,
                    anonymized_telemetry=False,
                )
            )
        return self._client

    def _get_or_create_collection(self, client: chromadb.Client):
        return client.get_or_create_collection(
            name=self._collection_name,
            metadata={"description": "Documents for RAG"},
        )

    def get_vector_store(self) -> Chroma | None:
        if self._vector_store is None:
            embedding_service = get_embedding_service()
            if not embedding_service.model:
                logger.error("Embedding model is not available")
                return None

            client = self._init_client()
            self._get_or_create_collection(client)

            from langchain.embeddings.base import Embeddings

            class SentenceTransformerEmbeddings(Embeddings):
                def __init__(self, model):
                    self.model = model

                def embed_documents(self, texts: list[str]) -> list[list[float]]:
                    embeddings = self.model.encode(
                        texts,
                        convert_to_numpy=True,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    )
                    return embeddings.tolist()

                def embed_query(self, text: str) -> list[float]:
                    embedding = self.model.encode(
                        text,
                        convert_to_numpy=True,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    )
                    return embedding.tolist()

            embeddings = SentenceTransformerEmbeddings(embedding_service.model)
            self._vector_store = Chroma(
                client=client,
                collection_name=self._collection_name,
                embedding_function=embeddings,
                persist_directory=self.persist_directory,
            )
            logger.info("RAG vector store initialized")

        return self._vector_store

    def add_documents(self, documents: list[Any], batch_size: int = 32) -> list[str]:
        if not documents:
            return []

        vector_store = self.get_vector_store()
        if vector_store is None:
            return []

        added_ids: list[str] = []
        total_docs = len(documents)
        logger.info("Adding %s docs to RAG store", total_docs)

        try:
            for i in range(0, total_docs, batch_size):
                batch = documents[i : i + batch_size]
                batch_ids = [str(uuid.uuid4()) for _ in batch]
                vector_store.add_documents(documents=batch, ids=batch_ids)
                added_ids.extend(batch_ids)
            return added_ids
        except Exception as e:
            logger.error("Failed to add docs: %s", e)
            return []

    def similarity_search(self, query: str, k: int = 4) -> list[Any]:
        vector_store = self.get_vector_store()
        if vector_store is None:
            return []
        try:
            return vector_store.similarity_search(query=query, k=k)
        except Exception as e:
            logger.error("Similarity search failed: %s", e)
            return []

    def get_stats(self) -> dict[str, Any]:
        try:
            client = self._init_client()
            collection = self._get_or_create_collection(client)
            count = collection.count()
        except Exception as e:
            logger.warning("Failed to get stats: %s", e)
            count = 0

        return {
            "total_documents": count,
            "collection_name": self._collection_name,
            "persist_directory": self.persist_directory,
        }

    def clear(self) -> bool:
        logger.warning("Clearing RAG vector store")
        try:
            client = self._init_client()
            try:
                client.delete_collection(name=self._collection_name)
            except Exception:
                pass
            self._get_or_create_collection(client)
            self._vector_store = None
            return True
        except Exception as e:
            logger.error("Failed to clear store: %s", e)
            return False


_rag_vector_store: RAGVectorStore | None = None


def get_rag_vector_store() -> RAGVectorStore:
    global _rag_vector_store
    if _rag_vector_store is None:
        _rag_vector_store = RAGVectorStore()
    return _rag_vector_store
