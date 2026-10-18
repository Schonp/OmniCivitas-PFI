import re
import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud.auditoria import registrar_auditoria
from app.db.crud.interacciones import primeros_mensajes_de_casos
from app.db.models import ActorInteraccion, Caso, EstadoCaso
from app.tools import ACTOR_AGENTE

# Cuántos casos recientes se miran para buscar coincidencia. Un ciudadano con
# más historial que esto es un caso de uso que no existe todavía (prototipo).
LIMITE_HISTORIAL = 20

# Igual que en la búsqueda de conocimiento: palabras de menos de 4 letras casi
# nunca son tema ("qué", "por", "mi") y solo generan falsos positivos.
MIN_LARGO_PALABRA = 4


def _normalizado(texto: str) -> str:
    """Minúsculas y sin acentos, para que "árbol" y "arbol" empaten."""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return sin_acentos.lower()


def _palabras(texto: str) -> set[str]:
    return {
        palabra
        for palabra in re.findall(r"[a-záéíóúñ0-9]+", _normalizado(texto))
        if len(palabra) >= MIN_LARGO_PALABRA
    }


def _referencia_mencionada(pista: str, caso: Caso) -> bool:
    """¿La pista trae la referencia del caso, entera o el sufijo alfanumérico
    (la gente escribe "8119ad18" sin el prefijo "REC-")?"""
    normalizada = _normalizado(pista).replace(" ", "").replace("-", "")
    referencia = _normalizado(caso.referencia).replace("-", "")
    if referencia in normalizada:
        return True
    sufijo = referencia[3:]  # sin el prefijo de 3 letras (REC/RES/CON/TRA)
    return len(sufijo) >= 6 and sufijo in normalizada


def _caso_a_dict(caso: Caso, primer_mensaje: str | None) -> dict:
    return {
        "referencia": caso.referencia,
        "caso_id": str(caso.id),
        "tipo": caso.tipo.value,
        "estado": caso.estado.value,
        "actualizado": caso.updated_at.isoformat(),
        "de_que_trata": caso.asunto or primer_mensaje,
    }


async def consultar_estado_caso(
    db: AsyncSession, *, ciudadano_id: uuid.UUID, referencia: str | None = None
) -> dict:
    """Busca el caso del ciudadano que coincide con `referencia` —su número o
    unas palabras de lo que escribió— en su historial reciente. Sin pista y
    con un solo caso sin cerrar, devuelve ese. Con más de uno y sin nada que
    los distinga, no adivina cuál: devuelve la lista para que se lo pregunten.

    Antes esto siempre devolvía "el caso más reciente", sin mirar de qué se
    trataba: un ciudadano con un reclamo viejo y una reserva nueva, preguntando
    por el reclamo, recibía el estado de la reserva y una respuesta segura de
    que estaba equivocado ("lo más reciente es una reserva, no un reclamo").
    """
    todos = list(
        (
            await db.execute(
                select(Caso)
                .where(Caso.ciudadano_id == ciudadano_id)
                .order_by(Caso.updated_at.desc())
                .limit(LIMITE_HISTORIAL)
            )
        )
        .scalars()
        .all()
    )
    if not todos:
        return {"tiene_casos": False, "mensaje": "El ciudadano no tiene casos registrados."}

    primeros = await primeros_mensajes_de_casos(db, [caso.id for caso in todos])

    coincidio_la_pista = False
    candidatos = todos
    if referencia and referencia.strip():
        por_numero = [c for c in todos if _referencia_mencionada(referencia, c)]
        if por_numero:
            candidatos, coincidio_la_pista = por_numero, True
        else:
            palabras_pista = _palabras(referencia)
            por_tema = (
                [c for c in todos if palabras_pista & _palabras(c.asunto or primeros.get(c.id) or "")]
                if palabras_pista
                else []
            )
            if por_tema:
                candidatos, coincidio_la_pista = por_tema, True

    if not coincidio_la_pista:
        # Sin pista, o sin nada que coincida con ella: por defecto se mira lo
        # que sigue en curso, no lo ya cerrado — es lo que más probablemente
        # está preguntando. Si no hay ninguno sin cerrar, ahí sí se ofrece el
        # historial entero (mejor que decirle que no tiene nada).
        candidatos = [c for c in todos if c.estado != EstadoCaso.cerrado] or todos

    if len(candidatos) > 1:
        return {
            "tiene_casos": True,
            "coincidio_la_pista": coincidio_la_pista,
            "varios_posibles": True,
            "casos": [_caso_a_dict(c, primeros.get(c.id)) for c in candidatos],
        }

    caso = candidatos[0]
    await registrar_auditoria(
        db,
        caso_id=caso.id,
        accion="consulta_estado",
        actor=ACTOR_AGENTE,
        actor_tipo=ActorInteraccion.agente_ia,
    )
    await db.commit()

    return {
        "tiene_casos": True,
        "coincidio_la_pista": coincidio_la_pista,
        "varios_posibles": False,
        **_caso_a_dict(caso, primeros.get(caso.id)),
    }
