"""
Тесты для конфигурации приложения.
"""

import pytest
from app.config import Settings, settings


class TestSettings:
    """Тесты для класса настроек."""

    def test_settings_singleton(self):
        """Проверка что settings является синглтоном."""
        assert settings is not None
        assert isinstance(settings, Settings)

    def test_embedding_model_name(self):
        """Проверка названия модели эмбеддингов."""
        assert settings.embedding_model_name == "all-MiniLM-L6-v2"

    def test_chroma_persist_directory(self):
        """Проверка директории для ChromaDB."""
        assert "data/db" in str(settings.chroma_persist_directory)

    def test_directories_exist(self):
        """Проверка существования директорий."""
        assert settings.data_dir.exists()
        assert settings.uploads_dir.exists()
        assert settings.db_dir.exists()

    def test_max_file_size_conversion(self):
        """Проверка конвертации размера файла."""
        expected_bytes = settings.max_file_size_mb * 1024 * 1024
        assert settings.max_file_size_bytes == expected_bytes

    def test_default_values(self):
        """Проверка значений по умолчанию."""
        assert settings.chunk_overlap > 0
        assert settings.max_chunk_size > settings.chunk_overlap
        assert settings.search_k > 0
        assert settings.port > 0


class TestSettingsWithEnv:
    """Тесты с переопределением переменных окружения."""

    def test_custom_embedding_model(self, monkeypatch):
        """Проверка загрузки кастомной модели эмбеддингов."""
        monkeypatch.setenv("EMBEDDING_MODEL_NAME", "test-model")
        custom_settings = Settings()
        assert custom_settings.embedding_model_name == "test-model"

    def test_custom_llm_url(self, monkeypatch):
        """Проверка загрузки кастомного URL LLM."""
        monkeypatch.setenv("LLM_API_BASE_URL", "http://custom.api.com/v1")
        custom_settings = Settings()
        assert custom_settings.llm_api_base_url == "http://custom.api.com/v1"
