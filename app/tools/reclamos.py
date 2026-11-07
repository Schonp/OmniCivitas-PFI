import uuid
from typing import Literal

from langchain_core.tools import ToolException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud.auditoria import registrar_auditoria
from app.db.crud.ciudadanos import obtener_ciudadano_por_id
from app.db.models import ActorInteraccion, Canal, Caso, TipoCaso
from app.tools import ACTOR_AGENTE

CategoriaReclamo = Literal["servicio", "infraestructura", "tramite"]


TITULO_MAX = 120


def titulo_de_reclamo(descripcion: str) -> str:
    """"Pozo en la calzada en Guatemala 4100": de qué se trata, sin repetir que
    es un reclamo (el tipo ya figura aparte en el panel y en el saludo)."""
    texto = " ".join(descripcion.split())
    if texto:
        texto = texto[0].upper() + texto[1:]
    return texto[:TITULO_MAX]


async def crear_reclamo(
    db: AsyncSession,
    *,
    ciudadano_id: uuid.UUID,
    canal: Canal,
    descripcion: str,
    categoria: CategoriaReclamo,
    caso_id: uuid.UUID | None = None,
) -> dict:
    if await obtener_ciudadano_por_id(db, ciudadano_id) is None:
        raise ToolException("Ciudadano no encontrado")

    # Si la conversación ya tenía un caso abierto para este reclamo —lo abrió
    # `_abrir_caso` en el primer mensaje, cuando todavía faltaba un dato para
    # poder ejecutar la tool—, se completa ese mismo caso. Sin este chequeo se
    # creaba uno nuevo cada vez que el ciudadano terminaba de dar el dato que
    # faltaba, y el mensaje final (con la dirección, por ejemplo) quedaba en un
    # caso aparte, desconectado del resto de la conversación.
    caso = await db.get(Caso, caso_id) if caso_id is not None else None
    si_reusa = caso is not None and caso.tipo == TipoCaso.reclamo
    if not si_reusa:
        caso = Caso(
            ciudadano_id=ciudadano_id,
            tipo=TipoCaso.reclamo,
            canal_origen=canal,
            canal_actual=canal,
        )
        db.add(caso)
        await db.flush()
    # La descripción es lo que identifica al reclamo cuando el ciudadano pregunta
    # por él ("su reclamo por pozo en la calzada..."). Si el caso ya tenía
    # asunto (el del correo, que escribió el propio ciudadano), se respeta.
    if not caso.asunto:
        caso.asunto = descripcion.strip()[:300]
    # El título no pisa uno que haya puesto el supervisor.
    if not caso.titulo:
        caso.titulo = titulo_de_reclamo(descripcion)

    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="creacion_reclamo",
        actor=ACTOR_AGENTE,
        actor_tipo=ActorInteraccion.agente_ia,
        metadata={"categoria": categoria},
    )
    await db.commit()
    await db.refresh(caso)

    return {
        "referencia": caso.referencia,
        "caso_id": str(caso.id),
        "tipo": caso.tipo.value,
        "estado": caso.estado.value,
        "categoria": categoria,
    }
