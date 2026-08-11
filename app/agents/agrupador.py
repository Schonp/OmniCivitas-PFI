import logging
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm
from app.db.models import Caso, EstadoCaso, GrupoReclamo, Interaccion, TipoCaso

logger = logging.getLogger(__name__)

SYSTEM_AGRUPADOR = """Sos un analista de una plataforma de atención ciudadana. Recibís \
una lista de reclamos abiertos, cada uno con su identificador y una descripción. \
Agrupá los que hablan del mismo problema de fondo (misma temática o misma zona), \
para que el organismo detecte problemas que afectan a varios vecinos.

- Cada grupo necesita al menos 2 reclamos: un reclamo sin pares no forma grupo.
- Un reclamo puede aparecer en un solo grupo.
- El tema del grupo es una frase corta y concreta (ej. "Falta de recolección en Caballito").
- Usá exactamente los identificadores recibidos, sin inventar ni modificar ninguno."""

MAX_RECLAMOS = 50
MAX_CARACTERES_DESCRIPCION = 300


class GrupoDetectado(BaseModel):
    tema: str = Field(description="Frase corta que describe el problema común")
    caso_ids: list[str] = Field(description="Identificadores de los reclamos del grupo")


class AgrupacionReclamos(BaseModel):
    grupos: list[GrupoDetectado] = Field(default_factory=list)


async def _reclamos_abiertos(db: AsyncSession) -> dict[str, str]:
    """id → primera descripción del ciudadano, de los reclamos no cerrados."""
    consulta = (
        select(Caso.id)
        .where(Caso.tipo == TipoCaso.reclamo, Caso.estado != EstadoCaso.cerrado)
        .order_by(Caso.created_at.desc())
        .limit(MAX_RECLAMOS)
    )
    ids = list((await db.execute(consulta)).scalars().all())
    if not ids:
        return {}

    filas = await db.execute(
        select(Interaccion.caso_id, Interaccion.contenido)
        .where(Interaccion.caso_id.in_(ids), Interaccion.interna.is_(False))
        .order_by(Interaccion.timestamp)
    )
    descripciones: dict[uuid.UUID, str] = {}
    for caso_id, contenido in filas:
        descripciones.setdefault(caso_id, contenido[:MAX_CARACTERES_DESCRIPCION])

    return {str(caso_id): descripciones.get(caso_id, "(sin descripción)") for caso_id in ids}


async def agrupar_reclamos(db: AsyncSession) -> list[GrupoReclamo]:
    """Reagrupa los reclamos abiertos con el LLM y reemplaza la foto anterior."""
    reclamos = await _reclamos_abiertos(db)

    grupos_validos: list[GrupoDetectado] = []
    if len(reclamos) >= 2:
        listado = "\n".join(f"- {caso_id}: {texto}" for caso_id, texto in reclamos.items())
        agrupador = llm.get_llm_intake().with_structured_output(AgrupacionReclamos)
        resultado: AgrupacionReclamos = await agrupador.ainvoke(
            [SystemMessage(content=SYSTEM_AGRUPADOR), HumanMessage(content=listado)]
        )
        # El LLM puede alucinar identificadores: solo sobreviven los reales.
        for grupo in resultado.grupos:
            ids_reales = [caso_id for caso_id in grupo.caso_ids if caso_id in reclamos]
            if len(ids_reales) >= 2:
                grupos_validos.append(GrupoDetectado(tema=grupo.tema, caso_ids=ids_reales))

    for grupo_anterior in (await db.execute(select(GrupoReclamo))).scalars().all():
        await db.delete(grupo_anterior)
    nuevos = [
        GrupoReclamo(tema=grupo.tema, caso_ids=grupo.caso_ids) for grupo in grupos_validos
    ]
    db.add_all(nuevos)
    await db.commit()
    for grupo in nuevos:
        await db.refresh(grupo)

    logger.debug("agrupador: %d reclamos → %d grupos", len(reclamos), len(nuevos))
    return nuevos
