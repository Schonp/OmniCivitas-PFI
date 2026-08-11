"""Métricas agregadas del panel.

La agregación se hace en Python sobre las filas del período: con el volumen de un
prototipo es despreciable y evita SQL con operadores JSON. Si el volumen creciera,
esto pasa a `GROUP BY` en Postgres sin cambiar la interfaz.
"""

import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud.casos import esperas_de_casos
from app.db.models import ActorInteraccion, Auditoria, Caso, EstadoCaso, Interaccion

ACCION_ESCALADO = "escalado"
ACCION_CAMBIO_CANAL = "cambio_canal"
ACCION_RESPUESTA_IA = "respuesta_ia"

DIAS_SERIE = 14


def _casos_por_dia(casos: list[Caso]) -> list[dict]:
    """Casos creados por día en las últimas dos semanas, con los días sin casos
    en cero para que la serie del gráfico no tenga huecos."""
    hoy = datetime.now(timezone.utc).date()
    inicio = hoy - timedelta(days=DIAS_SERIE - 1)
    conteo = Counter(
        caso.created_at.date() for caso in casos if caso.created_at.date() >= inicio
    )
    return [
        {"fecha": dia, "casos": conteo.get(dia, 0)}
        for dia in (inicio + timedelta(days=n) for n in range(DIAS_SERIE))
    ]


async def _minutos_primera_respuesta(
    db: AsyncSession, caso_ids: set[uuid.UUID] | None
) -> float | None:
    """Promedio de minutos entre el primer mensaje del ciudadano y la primera
    respuesta del agente, sobre los casos que tienen ambas puntas.
    Con `caso_ids` se limita a esos casos (la bandeja del operador)."""
    consulta = select(Interaccion.caso_id, Interaccion.actor, Interaccion.timestamp).where(
        Interaccion.actor.in_([ActorInteraccion.ciudadano, ActorInteraccion.agente_ia])
    )
    if caso_ids is not None:
        consulta = consulta.where(Interaccion.caso_id.in_(caso_ids))
    filas = await db.execute(consulta)

    primeras: dict[uuid.UUID, dict[str, datetime]] = defaultdict(dict)
    for caso_id, actor, momento in filas:
        previo = primeras[caso_id].get(actor.value)
        if previo is None or momento < previo:
            primeras[caso_id][actor.value] = momento

    demoras = []
    for marcas in primeras.values():
        consulta = marcas.get(ActorInteraccion.ciudadano.value)
        respuesta = marcas.get(ActorInteraccion.agente_ia.value)
        if consulta is not None and respuesta is not None and respuesta >= consulta:
            demoras.append((respuesta - consulta).total_seconds() / 60)

    if not demoras:
        return None
    return round(sum(demoras) / len(demoras), 1)


async def calcular_metricas(
    db: AsyncSession,
    *,
    operador_id: uuid.UUID | None = None,
    horas_espera: int = 24,
) -> dict:
    """Con `operador_id`, todas las métricas se calculan solo sobre su bandeja:
    el operador ve sus números, el supervisor los del organismo."""
    consulta_casos = select(Caso)
    if operador_id is not None:
        consulta_casos = consulta_casos.where(Caso.operador_asignado_id == operador_id)
    casos = list((await db.execute(consulta_casos)).scalars().all())
    total = len(casos)
    ids_visibles = {caso.id for caso in casos} if operador_id is not None else None

    abiertos = [caso for caso in casos if caso.estado != EstadoCaso.cerrado]
    esperas = await esperas_de_casos(db, abiertos)
    limite = datetime.now(timezone.utc) - timedelta(hours=horas_espera)
    sin_responder = [momento for momento in esperas.values() if momento is not None]

    consulta_auditorias = select(Auditoria.caso_id, Auditoria.accion, Auditoria.metadata_)
    if ids_visibles is not None:
        consulta_auditorias = consulta_auditorias.where(Auditoria.caso_id.in_(ids_visibles))
    auditorias = await db.execute(consulta_auditorias)
    escalados: set[uuid.UUID] = set()
    cambios_de_canal: set[uuid.UUID] = set()
    confianzas: list[float] = []

    for caso_id, accion, metadata in auditorias:
        if accion == ACCION_ESCALADO:
            escalados.add(caso_id)
        elif accion == ACCION_CAMBIO_CANAL:
            cambios_de_canal.add(caso_id)
        if accion == ACCION_RESPUESTA_IA and isinstance(metadata, dict):
            confianza = metadata.get("confianza")
            if isinstance(confianza, (int, float)):
                confianzas.append(float(confianza))

    # Un caso cuenta como automatizado si nunca necesitó a un humano. La verdad la
    # tiene la auditoría, no el estado actual: un caso escalado y después cerrado
    # sigue habiendo requerido intervención.
    resueltos_por_ia = total - len(escalados)

    return {
        "total_casos": total,
        "por_estado": Counter(caso.estado.value for caso in casos),
        "por_canal": Counter(caso.canal_actual.value for caso in casos),
        "por_tipo": Counter(caso.tipo.value for caso in casos),
        "escalados": len(escalados),
        "resueltos_por_ia": resueltos_por_ia,
        "tasa_automatizacion": round(resueltos_por_ia / total, 3) if total else None,
        "casos_con_cambio_canal": len(cambios_de_canal),
        "casos_esperando_respuesta": len(sin_responder),
        "casos_demorados": sum(1 for momento in sin_responder if momento < limite),
        "horas_umbral_demora": horas_espera,
        "minutos_primera_respuesta": await _minutos_primera_respuesta(db, ids_visibles),
        "confianza_promedio": round(sum(confianzas) / len(confianzas), 3)
        if confianzas
        else None,
        "casos_por_dia": _casos_por_dia(casos),
    }
