"""
Конфигурация pytest для проекта RAG.
"""

import sys
from pathlib import Path

# Добавление корня проекта в путь
sys.path.insert(0, str(Path(__file__).parent.parent))


# Настройки pytest
pytest_plugins = []


def pytest_configure(config):
    """Конфигурация pytest перед запуском тестов."""
    # Маркировка тестов
    config.addinivalue_line(
        "markers",
        "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    )
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests",
    )
