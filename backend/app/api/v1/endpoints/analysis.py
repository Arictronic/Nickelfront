from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models.analysis_result import AnalysisResult
from app.services.analysis_pipeline import AnalysisPipelineService
from app.services.analysis_export import export_analysis_to_excel
from shared.schemas.auth import UserResponse

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/{paper_id}/context")
async def get_analysis_context(
    paper_id: int = Path(..., description="ID статьи"),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AnalysisPipelineService(db)
    context = await service.build_context(paper_id)
    if not context:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return context


@router.post("/{paper_id}/run")
async def run_analysis(
    paper_id: int = Path(..., description="ID статьи"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AnalysisPipelineService(db)
    try:
        result = await service.run_analysis(paper_id, user_id=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "id": result.id,
        "paper_id": result.paper_id,
        "status": result.status,
        "error_message": result.error_message,
    }


@router.get("/results")
async def list_analysis_results(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    stmt = (
        select(AnalysisResult)
        .where(AnalysisResult.user_id == current_user.id)
        .order_by(AnalysisResult.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    entries = result.scalars().all()
    return [
        {
            "id": e.id,
            "paper_id": e.paper_id,
            "status": e.status,
            "prompt_version": e.prompt_version,
            "created_at": str(e.created_at) if e.created_at else None,
            "completed_at": str(e.completed_at) if e.completed_at else None,
            "error_message": e.error_message,
        }
        for e in entries
    ]


@router.get("/{analysis_id}/export")
async def export_analysis(
    analysis_id: int = Path(..., description="ID результата анализа"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        buffer = await export_analysis_to_excel(analysis_id, db, user_id=current_user.id)
        return Response(
            content=buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=analysis_{analysis_id}.xlsx"
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Сервис экспорта недоступен: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка экспорта: {str(e)}")
