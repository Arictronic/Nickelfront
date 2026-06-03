"""API endpoints для экспорта отчётов."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.endpoints.error_helpers import format_paper_db_error
from app.db.session import get_db
from app.services.paper_service import PaperService
from app.services.report_service import generate_paper_docx, generate_paper_pdf, generate_paper_report
from shared.schemas.auth import UserResponse

router = APIRouter(prefix="/reports", tags=["reports"])


def _paper_to_report_dict(paper) -> dict:
    return {
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



async def _load_paper_or_404(paper_id: int, db: AsyncSession):
    try:
        paper_service = PaperService(db)
        paper = await paper_service.get_by_id(paper_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return paper


@router.get("/paper/{paper_id}/pdf")
async def export_paper_pdf(
    paper_id: int = Path(..., description="ID статьи"),
    _current_user: UserResponse = Depends(get_current_user),
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
        paper = await _load_paper_or_404(paper_id, db)
        paper_dict = _paper_to_report_dict(paper)


        pdf_bytes = await asyncio.to_thread(generate_paper_pdf, paper_dict)

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=paper_{paper_id}_report.pdf"
            }
        )

    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Сервис отчётов недоступен: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка генерации отчёта: {str(e)}")


@router.get("/paper/{paper_id}/docx")
async def export_paper_docx(
    paper_id: int = Path(..., description="ID статьи"),
    _current_user: UserResponse = Depends(get_current_user),
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
        paper = await _load_paper_or_404(paper_id, db)
        paper_dict = _paper_to_report_dict(paper)


        docx_bytes = await asyncio.to_thread(generate_paper_docx, paper_dict)

        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename=paper_{paper_id}_report.docx"
            }
        )

    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Сервис отчётов недоступен: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка генерации отчёта: {str(e)}")


@router.get("/paper/{paper_id}")
async def get_paper_report(
    paper_id: int = Path(..., description="ID статьи"),
    _current_user: UserResponse = Depends(get_current_user),
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
        paper = await _load_paper_or_404(paper_id, db)


        report = await asyncio.to_thread(generate_paper_report, _paper_to_report_dict(paper))
        return report

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения отчёта: {str(e)}")
