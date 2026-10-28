"""Recordatorio de turno, el día anterior, por el canal del ciudadano.

Lo manda el script `scripts/enviar_recordatorios.py` (pensado para correr una
vez por día) o el supervisor desde el panel. A quien escribió por WhatsApp en
las últimas 24 horas le llega como mensaje común; a los demás, dentro de la
plantilla de seguimiento, que es la única forma que admite Meta de escribirle a
alguien fuera de esa ventana. Un recordatorio que no salió no se marca como
enviado: el próximo envío lo vuelve a intentar.
"""

import logging
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.confirmacion import recordatorio_de_turno
from app.channels.salida import canal_de_envio, enviar_al_ciudadano
from app.db.crud.auditoria import registrar_auditoria
from app.db.crud.interacciones import crear_interaccion, ultimo_mensaje_por_whatsapp
from app.db.crud.turnos import ahora_local, reservas_para_recordar
from app.db.models import ActorInteraccion
from app.tools import ACTOR_AGENTE

logger = logging.getLogger(__name__)


async def enviar_recordatorios(db: AsyncSession, dia: date | None = None) -> dict:
    """Recuerda los turnos confirmados de `dia` (por defecto, mañana)."""
    dia = dia or ahora_local().date() + timedelta(days=1)
    reservas = await reservas_para_recordar(db, dia)
    enviados = 0
    no_enviados = []
    for reserva in reservas:
        texto = recordatorio_de_turno(reserva)
        canal = canal_de_envio(reserva.caso.canal_actual)
        resultado = await enviar_al_ciudadano(
            canal,
            reserva.ciudadano,
            texto,
            ultimo_entrante=await ultimo_mensaje_por_whatsapp(db, reserva.ciudadano_id),
        )
        await registrar_auditoria(
            db,
            caso_id=reserva.caso_id,
            accion="recordatorio_turno",
            actor=ACTOR_AGENTE,
            actor_tipo=ActorInteraccion.agente_ia,
            metadata={"canal": canal.value, **resultado.como_metadata()},
        )
        if resultado.transmitido:
            reserva.recordatorio_enviado_en = ahora_local()
            await crear_interaccion(
                db,
                caso_id=reserva.caso_id,
                contenido=texto,
                canal=canal,
                actor=ActorInteraccion.agente_ia,
            )
            enviados += 1
        else:
            no_enviados.append({"referencia": reserva.caso.referencia, "motivo": resultado.motivo})
        await db.commit()
    logger.info("recordatorios del %s: %d enviados de %d", dia, enviados, len(reservas))
    return {"dia": dia, "total": len(reservas), "enviados": enviados, "no_enviados": no_enviados}
