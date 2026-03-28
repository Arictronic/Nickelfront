"""API endpoints для RAG (Retrieval-Augmented Generation)."""

import asyncio

from fastapi import APIRouter, File, HTTPException, UploadFile
from loguru import logger
from pydantic import BaseModel, Field

from app.services.rag_chain import process_query
from app.services.rag_parser import pdf_parser
from app.services.rag_vector_store import get_rag_vector_store

router = APIRouter(prefix="/rag", tags=["rag"])


class AskRequest(BaseModel):
    """Запрос на вопрос к RAG."""

    question: str = Field(..., min_length=1, max_length=5000, description="Вопрос")
    include_sources: bool = Field(default=True, description="Включать источники")
    include_scores: bool = Field(default=False, description="Включать оценки")


class AskResponse(BaseModel):
    """Ответ RAG."""

    answer: str = Field(..., description="Ответ")
    question: str = Field(..., description="Вопрос")
    sources: list[dict] = Field(default_factory=list, description="Источники")
    documents_found: int = Field(default=0, description="Найдено документов")
    error: str | None = Field(None, description="Ошибка")


class UploadResponse(BaseModel):
    """Ответ на загрузку файла."""

    message: str
    filename: str
    documents_count: int
    chunks_count: int


class StatsResponse(BaseModel):
    """Статистика RAG."""

    total_documents: int
    collection_name: str
    persist_directory: str


@router.post("/ask", response_model=AskResponse)
async def ask_question(request: AskRequest):
    """
    Задать вопрос по загруженным документам.

    RAG-система найдёт релевантные документы и сгенерирует ответ
    на основе контекста.
    """
    logger.info(f"Получен вопрос: {request.question[:100]}...")

    try:
        result = await asyncio.to_thread(process_query, request.question)

        if result.get("error"):
            return AskResponse(
                answer="",
                question=request.question,
                sources=[],
                documents_found=0,
                error=result["error"],
            )

        sources = []
        if request.include_sources:
            for doc in result.get("source_documents", []):
                sources.append({
                    "index": doc.get("index", 0),
                    "content": doc.get("content", "")[:500],
                    "metadata": doc.get("metadata", {}),
                })

        return AskResponse(
            answer=result.get("result", ""),
            question=result.get("query", request.question),
            sources=sources,
            documents_found=len(sources),
        )

    except Exception as e:
        logger.error(f"Ошибка обработки вопроса: {e}", exc_info=True)
        return AskResponse(
            answer="",
            question=request.question,
            sources=[],
            documents_found=0,
            error=str(e),
        )


@router.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """
    Загрузить PDF документ для RAG.

    Файл будет обработан, текст извлечён и сохранён в векторной базе.
    """
    logger.info(f"Получен файл для загрузки: {file.filename}")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=415,
            detail="Поддерживаются только PDF файлы",
        )

    try:
        file_bytes = await file.read()

        if len(file_bytes) == 0:
            raise HTTPException(status_code=400, detail="Файл пуст")

        if len(file_bytes) > 50 * 1024 * 1024:  # 50 MB
            raise HTTPException(status_code=413, detail="Файл слишком большой")

        logger.info(f"Парсинг PDF: {file.filename} ({len(file_bytes)} байт)")

        documents = await asyncio.to_thread(
            pdf_parser.parse_bytes_to_documents,
            file_bytes=file_bytes,
            filename=file.filename,
        )

        if not documents:
            raise HTTPException(
                status_code=400,
                detail="Не удалось извлечь текст из PDF",
            )

        vector_store = get_rag_vector_store()
        added_ids = await asyncio.to_thread(vector_store.add_documents, documents)

        logger.info(f"Файл успешно обработан: {file.filename}")

        return UploadResponse(
            message="Файл успешно загружен и обработан",
            filename=file.filename,
            documents_count=len(documents),
            chunks_count=len(added_ids),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при обработке файла: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка обработки файла: {str(e)}",
        )


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Получить статистику RAG системы."""
    vector_store = get_rag_vector_store()
    stats = await asyncio.to_thread(vector_store.get_stats)

    return StatsResponse(
        total_documents=stats["total_documents"],
        collection_name=stats["collection_name"],
        persist_directory=stats["persist_directory"],
    )


@router.post("/clear")
async def clear_store():
    """
    Очистить векторное хранилище RAG.

    Внимание: Эта операция необратима!
    """
    logger.warning("Запрос на очистку RAG хранилища")

    vector_store = get_rag_vector_store()
    success = await asyncio.to_thread(vector_store.clear)

    if success:
        return {"message": "RAG хранилище очищено", "success": True}
    else:
        raise HTTPException(status_code=500, detail="Не удалось очистить хранилище")
