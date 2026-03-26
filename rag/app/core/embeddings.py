"""
Модуль работы с эмбеддингами.

Предоставляет функции для создания и кэширования модели эмбеддингов
на основе sentence-transformers с оптимизацией под ограниченную память.
"""

import logging
from functools import lru_cache

from langchain_community.embeddings import HuggingFaceEmbeddings

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_embeddings_model() -> HuggingFaceEmbeddings:
    """
    Возвращает модель эмбеддингов с кэшированием.

    Использует легковесную модель sentence-transformers (all-MiniLM-L6-v2),
    оптимизированную для работы с ограниченной памятью (~4 ГБ RAM).
    Модель загружается только один раз и кэшируется для повторного использования.

    Returns:
        HuggingFaceEmbeddings: Инициализированная модель эмбеддингов.

    Note:
        Функция использует lru_cache для предотвращения повторной загрузки модели.
        Это критично для экономии памяти при ограниченных ресурсах.
    """
    logger.info(f"Загрузка модели эмбеддингов: {settings.embedding_model_name}")

    model_kwargs = {
        "device": settings.embedding_device,
        "trust_remote_code": False,
    }

    encode_kwargs = {
        "normalize_embeddings": True,
        "batch_size": 8,
        "show_progress_bar": False,
    }

    embeddings = HuggingFaceEmbeddings(
        model_name=settings.embedding_model_name,
        model_kwargs=model_kwargs,
        encode_kwargs=encode_kwargs,
    )

    logger.info("Модель эмбеддингов успешно загружена")
    return embeddings
