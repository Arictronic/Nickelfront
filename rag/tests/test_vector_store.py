"""
Тесты для векторного хранилища и эмбеддингов.
"""

import pytest
from langchain.schema import Document

from app.core.embeddings import get_embeddings_model
from app.core.vector_store import (
    VectorStoreManager,
    vector_store_manager,
)


class TestEmbeddings:
    """Тесты для модуля эмбеддингов."""

    def test_get_embeddings_model_cached(self):
        """Проверка кэширования модели эмбеддингов."""
        model1 = get_embeddings_model()
        model2 = get_embeddings_model()
        assert model1 is model2  # Один и тот же объект благодаря lru_cache


class TestVectorStoreManager:
    """Тесты для менеджера векторного хранилища."""

    @pytest.fixture
    def vector_store(self):
        """Фикстура с временным векторным хранилищем."""
        vs = VectorStoreManager(persist_directory="./data/test_db")
        yield vs
        # Очистка после теста
        vs.clear()

    def test_add_documents(self, vector_store):
        """Проверка добавления документов."""
        docs = [
            Document(page_content="Тестовый контент 1", metadata={"source": "test1.pdf"}),
            Document(page_content="Тестовый контент 2", metadata={"source": "test2.pdf"}),
        ]

        ids = vector_store.add_documents(docs)
        assert len(ids) == 2

    def test_add_empty_documents(self, vector_store):
        """Проверка добавления пустого списка документов."""
        ids = vector_store.add_documents([])
        assert ids == []

    def test_similarity_search(self, vector_store):
        """Проверка поиска похожих документов."""
        # Добавление тестовых документов
        docs = [
            Document(page_content="Никелевые суперсплавы содержат никель", metadata={}),
            Document(page_content="Хром улучшает коррозионную стойкость", metadata={}),
        ]
        vector_store.add_documents(docs)

        # Поиск
        results = vector_store.similarity_search("никель", k=2)
        assert len(results) > 0

    def test_similarity_search_empty_db(self, vector_store):
        """Проверка поиска в пустой базе."""
        results = vector_store.similarity_search("запрос")
        assert results == []

    def test_get_stats(self, vector_store):
        """Проверка получения статистики."""
        stats = vector_store.get_stats()

        assert "total_documents" in stats
        assert "collection_name" in stats
        assert "persist_directory" in stats
        assert stats["collection_name"] == "patents_collection"

    def test_clear_store(self, vector_store):
        """Проверка очистки хранилища."""
        # Добавление документа
        docs = [Document(page_content="Тест", metadata={})]
        vector_store.add_documents(docs)

        # Очистка
        result = vector_store.clear()
        assert result is True

        # Проверка что база пуста
        stats = vector_store.get_stats()
        assert stats["total_documents"] == 0
