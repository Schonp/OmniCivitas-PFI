from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.crud.metricas import calcular_metricas
from app.db.models import RolUsuario, Usuario
from app.db.session import get_db
from app.schemas.metricas import MetricasPanel

router = APIRouter(prefix="/api/metricas", tags=["metricas"])


@router.get("", response_model=MetricasPanel)
async def metricas(
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
) -> MetricasPanel:
    """Métricas del organismo para el supervisor; solo de su bandeja para el operador."""
    operador_id = usuario_actual.id if usuario_actual.rol == RolUsuario.operador else None
    return MetricasPanel(**await calcular_metricas(db, operador_id=operador_id))
