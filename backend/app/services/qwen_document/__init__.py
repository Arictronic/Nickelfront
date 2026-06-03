"""Small, side-effect-light helpers for Qwen document processing.

The Celery tasks keep orchestration, database updates and queue contracts.
This package contains reusable context, prompt, result, session and document
helpers that are safe to import without importing Celery task modules.
"""
