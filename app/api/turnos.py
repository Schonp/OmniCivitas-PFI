from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.crud.turnos import listar_turnos_con_reservas
from app.db.models import Usuario
from app.db.session import get_db
from app.schemas.turno import TurnoOut

router = APIRouter(prefix="/api/turnos", tags=["turnos"])


@router.get("", response_model=list[TurnoOut])
async def listar(
    db: AsyncSession = Depends(get_db),
    _usuario: Usuario = Depends(get_current_user),
) -> list[TurnoOut]:
    """Agendas de turnos con sus reservas, para verificar las reservas del agente."""
    return [TurnoOut.model_validate(turno) for turno in await listar_turnos_con_reservas(db)]
