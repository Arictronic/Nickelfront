"""API endpoints для экспорта отчётов."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.paper_service import PaperService
from app.services.report_service import generate_paper_docx, generate_paper_pdf

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/paper/{paper_id}/pdf")
async def export_paper_pdf(
    paper_id: int = Path(..., description="ID статьи"),
    db: AsyncSession = Depends(get_db),
):
    """
    Экспортировать отчёт по статье в PDF.

    Args:
        paper_id: ID статьи

    Returns:
        PDF файл
    """
    try:
        # Получаем статью
        paper_service = PaperService(db)
        paper = await paper_service.get_by_id(paper_id)

        if not paper:
            raise HTTPException(status_code=404, detail="Статья не найдена")

        # Конвертируем SQLAlchemy модель в dict
        paper_dict = {
            "id": paper.id,
            "title": paper.title,
            "authors": paper.authors or [],
            "publication_date": str(paper.publication_date) if paper.publication_date else None,
            "journal": paper.journal,
            "doi": paper.doi,
            "source": paper.source,
            "url": paper.url,
            "abstract": paper.abstract,
            "full_text": paper.full_text,
            "keywords": paper.keywords or [],
        }

        # Генерируем PDF
        pdf_bytes = await asyncio.to_thread(generate_paper_pdf, paper_dict)

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=paper_{paper_id}_report.pdf"
            }
        )

    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Сервис отчётов недоступен: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка генерации отчёта: {str(e)}")


@router.get("/paper/{paper_id}/docx")
async def export_paper_docx(
    paper_id: int = Path(..., description="ID статьи"),
    db: AsyncSession = Depends(get_db),
):
    """
    Экспортировать отчёт по статье в DOCX.

    Args:
        paper_id: ID статьи

    Returns:
        DOCX файл
    """
    try:
        # Получаем статью
        paper_service = PaperService(db)
        paper = await paper_service.get_by_id(paper_id)

        if not paper:
            raise HTTPException(status_code=404, detail="Статья не найдена")

        # Конвертируем SQLAlchemy модель в dict
        paper_dict = {
            "id": paper.id,
            "title": paper.title,
            "authors": paper.authors or [],
            "publication_date": str(paper.publication_date) if paper.publication_date else None,
            "journal": paper.journal,
            "doi": paper.doi,
            "source": paper.source,
            "url": paper.url,
            "abstract": paper.abstract,
            "full_text": paper.full_text,
            "keywords": paper.keywords or [],
        }

        # Генерируем DOCX
        docx_bytes = await asyncio.to_thread(generate_paper_docx, paper_dict)

        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename=paper_{paper_id}_report.docx"
            }
        )

    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Сервис отчётов недоступен: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка генерации отчёта: {str(e)}")


@router.get("/paper/{paper_id}")
async def get_paper_report(
    paper_id: int = Path(..., description="ID статьи"),
    db: AsyncSession = Depends(get_db),
):
    """
    Получить отчёт по статье в JSON формате.

    Args:
        paper_id: ID статьи

    Returns:
        JSON с отчётом
    """
    try:
        # Получаем статью
        paper_service = PaperService(db)
        paper = await paper_service.get_by_id(paper_id)

        if not paper:
            raise HTTPException(status_code=404, detail="Статья не найдена")

        # Импортируем сервис отчётов из analytics
        try:
            from analytics.reports import generate_paper_report

            paper_dict = {
                "id": paper.id,
                "title": paper.title,
                "authors": paper.authors or [],
                "publication_date": str(paper.publication_date) if paper.publication_date else None,
                "journal": paper.journal,
                "doi": paper.doi,
                "source": paper.source,
                "url": paper.url,
                "abstract": paper.abstract,
                "full_text": paper.full_text,
                "keywords": paper.keywords or [],
            }

            report = await asyncio.to_thread(generate_paper_report, paper_dict)

            return report

        except ImportError:
            # Fallback если analytics модуль недоступен
            return {
                "paper_id": paper.id,
                "title": paper.title,
                "authors": paper.authors or [],
                "journal": paper.journal,
                "publication_date": str(paper.publication_date) if paper.publication_date else None,
                "doi": paper.doi,
                "source": paper.source,
                "abstract_length": len(paper.abstract) if paper.abstract else 0,
                "full_text_length": len(paper.full_text) if paper.full_text else 0,
                "keywords_count": len(paper.keywords) if paper.keywords else 0,
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения отчёта: {str(e)}")
