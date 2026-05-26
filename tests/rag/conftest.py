"""
Конфигурация pytest для проекта RAG.
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))



def pytest_configure(config):
    """Конфигурация pytest перед запуском тестов."""

    config.addinivalue_line(
        "markers",
        "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    )
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests",
    )
