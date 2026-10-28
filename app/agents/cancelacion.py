"""Cancelación y cambio de horario de un turno, pedidos por el propio ciudadano.

Se resuelven en el código y no con el modelo: el modelo local no se entrenó con
herramientas para esto, y cancelar o mover el turno equivocado es peor que no
hacerlo. El pedido se reconoce por sus palabras ("cancelar", "no voy a poder
ir", "cambiar mi turno" junto a "turno"); el turno, por su número de caso, por
el nombre del trámite o porque es el único que tiene pendiente; y el horario
nuevo, con el lector de días y horas de `app/agents/fechas.py`. Si hay más de un
turno y nada los distingue, se le pregunta cuál.
"""

import re
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.confirmacion import (
    MARCA_CAMBIO_NO_DISPONIBLE,
    cambio_no_disponible,
    pedido_de_nuevo_horario,
    sin_turnos_pendientes,
    turno_cancelado,
    turno_reprogramado,
    turnos_para_elegir,
)
from app.agents.fechas import fecha_hora_dicha, hora_dicha
from app.agents.state import AgentState
from app.db.crud.turnos import (
    ReservaNoDisponible,
    ahora_local,
    cancelar_reserva,
    reprogramar_reserva,
    reservas_vigentes_del_ciudadano,
)
from app.db.models import ActorInteraccion, Canal, Reserva
from app.tools import ACTOR_AGENTE

_CANCELAR = re.compile(
    r"\b(cancel\w*|anul\w*|dar de baja|doy de baja|no (voy a|puedo|podr[eé]) (poder )?ir)\b",
    re.IGNORECASE,
)
# El verbo pegado al turno: "cambiar mi turno", "pasame el turno", "mover la
# reserva". Sin esa cercanía, "un turno para cambiar el domicilio del DNI" se
# leería como un pedido de cambio.
_REPROGRAMAR = re.compile(
    r"\b(cambi\w*|mov\w*|reprogram\w*|pas[aá]\w*|corr\w*)\s+(?:\w+\s+){0,2}(turno|reserva|cita)\b",
    re.IGNORECASE,
)
_TURNO = re.compile(r"\b(turno|turnos|reserva|reservas|cita)\b", re.IGNORECASE)
_REFERENCIA = re.compile(r"\bRES-?([0-9A-F]{8})\b", re.IGNORECASE)
# Palabras de los nombres de agenda que no sirven para distinguir una de otra.
_GENERICAS = {"de", "del", "la", "el", "en", "y", "turno", "turnos", "atención", "atencion", "renovación", "renovacion"}


def pide_cancelar_turno(mensaje: str | None) -> bool:
    texto = mensaje or ""
    return bool(_CANCELAR.search(texto) and (_TURNO.search(texto) or _REFERENCIA.search(texto)))


def pide_cambiar_turno(mensaje: str | None) -> bool:
    return bool(_REPROGRAMAR.search(mensaje or ""))


def _ultimo_del_agente(state: AgentState) -> str | None:
    return next(
        (
            e.get("contenido") or ""
            for e in reversed(state.get("historial") or [])
            if e.get("actor") == ActorInteraccion.agente_ia.value
        ),
        None,
    )


def eleccion_de_horario_ofrecido(state: AgentState) -> datetime | None:
    """El horario que elige el ciudadano entre los que se le ofrecieron para
    cambiar su turno ("el de las 10:30"), si el mensaje anterior del agente fue
    ese ofrecimiento."""
    ofrecimiento = _ultimo_del_agente(state)
    if not ofrecimiento or MARCA_CAMBIO_NO_DISPONIBLE not in ofrecimiento:
        return None
    ahora = ahora_local()
    completo = fecha_hora_dicha(state.get("mensaje") or "", ahora)
    if completo is not None:
        return completo
    hora = hora_dicha(state.get("mensaje") or "")
    if hora is None:
        return None
    for linea in ofrecimiento.splitlines():
        ofrecido = fecha_hora_dicha(linea, ahora)
        if ofrecido is not None and ofrecido.time() == hora:
            return ofrecido
    return None


def es_gestion_de_turno(state: AgentState) -> bool:
    """Si el mensaje es para cancelar o cambiar un turno: lo resuelve el código."""
    mensaje = state.get("mensaje")
    return (
        pide_cancelar_turno(mensaje)
        or pide_cambiar_turno(mensaje)
        or eleccion_de_horario_ofrecido(state) is not None
    )


def _elegir(reservas: list[Reserva], texto: str) -> list[Reserva]:
    """Las reservas a las que se refiere el texto, de más a menos precisa."""
    referencia = _REFERENCIA.search(texto)
    if referencia:
        sufijo = referencia.group(1).upper()
        return [r for r in reservas if r.caso.referencia.endswith(sufijo)]
    minusculas = texto.lower()
    por_tramite = [
        r
        for r in reservas
        if any(
            palabra in minusculas
            for palabra in re.findall(r"\w+", r.turno.nombre.lower())
            if palabra not in _GENERICAS and len(palabra) >= 3
        )
    ]
    return por_tramite or reservas


async def atender_turno(state: AgentState, db: AsyncSession) -> dict | None:
    """La respuesta al pedido de cancelar o cambiar un turno, o None si el
    mensaje no es ninguno de los dos."""
    if not state.get("ciudadano_id"):
        return None
    eleccion = eleccion_de_horario_ofrecido(state)
    cambiar = eleccion is not None or pide_cambiar_turno(state.get("mensaje"))
    if not cambiar and not pide_cancelar_turno(state.get("mensaje")):
        return None

    canal = Canal(state["canal"])
    vigentes = await reservas_vigentes_del_ciudadano(db, uuid.UUID(state["ciudadano_id"]))
    if not vigentes:
        return {"caso_id": state.get("caso_id"), "respuesta": sin_turnos_pendientes(canal, cambiar)}

    # Si elige entre horarios ofrecidos, el turno es el que nombra ese ofrecimiento.
    texto = _ultimo_del_agente(state) if eleccion is not None else state["mensaje"]
    candidatas = _elegir(vigentes, texto or "")
    if len(candidatas) != 1:
        return {
            "caso_id": state.get("caso_id"),
            "respuesta": turnos_para_elegir(candidatas or vigentes, canal, cambiar),
        }
    reserva = candidatas[0]
    if cambiar:
        return await _cambiar(db, reserva, eleccion or fecha_hora_dicha(state["mensaje"], ahora_local()), canal)
    return await _cancelar(db, reserva, canal)


async def _cancelar(db: AsyncSession, reserva: Reserva, canal: Canal) -> dict:
    await cancelar_reserva(
        db,
        reserva,
        actor=ACTOR_AGENTE,
        actor_tipo=ActorInteraccion.agente_ia,
        motivo="Pedido del ciudadano",
    )
    # Todo lo que se lee de la reserva va antes del commit, que la expira.
    resultado = {
        "caso_id": str(reserva.caso_id),
        "resultado_ejecucion": {"cancelar_turno": {"reserva_id": str(reserva.id)}},
        "respuesta": turno_cancelado(reserva, canal),
    }
    await db.commit()
    return resultado


async def _cambiar(db: AsyncSession, reserva: Reserva, momento: datetime | None, canal: Canal) -> dict:
    if momento is None:
        return {"caso_id": str(reserva.caso_id), "respuesta": pedido_de_nuevo_horario(reserva, canal)}
    try:
        anterior = await reprogramar_reserva(
            db, reserva, momento, actor=ACTOR_AGENTE, actor_tipo=ActorInteraccion.agente_ia
        )
    except ReservaNoDisponible as error:
        return {
            "caso_id": str(reserva.caso_id),
            "respuesta": cambio_no_disponible(reserva, error.motivo, error.alternativas, canal),
        }
    resultado = {
        "caso_id": str(reserva.caso_id),
        "resultado_ejecucion": {"reprogramar_turno": {"reserva_id": str(reserva.id)}},
        "respuesta": turno_reprogramado(reserva, anterior, canal),
    }
    await db.commit()
    return resultado
