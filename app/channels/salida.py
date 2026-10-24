"""Envío saliente por el canal del caso.

El grafo transmite sus propias respuestas desde cada canal, pero el operador
responde desde el panel, fuera de esa conversación. Este módulo es el punto
único que decide por dónde alcanzar al ciudadano según el canal actual del caso.

No lanza excepciones hacia el endpoint: la interacción ya quedó persistida y
perder la respuesta del operador por una falla de SMTP sería peor que
registrarla y avisar. El resultado se devuelve para que quede auditado.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import email as canal_email
from app.channels import whatsapp
from app.core.config import settings
from app.agents.escalado import escalar_caso_por_falla
from app.db.crud.auditoria import registrar_auditoria
from app.db.models import ActorInteraccion, Canal, Ciudadano

logger = logging.getLogger(__name__)

ACTOR_AGENTE = "agente_ia"


def canal_de_envio(canal: Canal) -> Canal:
    """Por dónde sale una respuesta escrita para un caso de ese canal.

    No hay operadores atendiendo por teléfono: un caso que llegó por voz se
    sigue por WhatsApp, al mismo número desde el que llamó el ciudadano, como
    le anticipa el aviso de derivación de la llamada.
    """
    return Canal.whatsapp if canal == Canal.voz else canal


def dentro_de_ventana(ultimo_entrante: datetime | None) -> bool:
    """WhatsApp solo admite mensajes libres dentro de las 24 horas posteriores
    al último mensaje del ciudadano; después hace falta una plantilla aprobada
    por Meta. Es una regla de la plataforma, no del proveedor.

    Se chequea antes de intentar el envío para que el operador se entere por la
    auditoría, en vez de que Meta lo rechace y el vecino nunca reciba nada.
    """
    if ultimo_entrante is None:
        return False
    if ultimo_entrante.tzinfo is None:
        ultimo_entrante = ultimo_entrante.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - ultimo_entrante < timedelta(
        hours=whatsapp.VENTANA_HORAS
    )


def _asunto_respuesta(asunto: str | None) -> str:
    if not asunto:
        return canal_email.ASUNTO_RESPUESTA
    limpio = asunto.strip()
    return limpio if limpio.lower().startswith("re:") else f"Re: {limpio}"


@dataclass(frozen=True)
class ResultadoEnvio:
    transmitido: bool
    motivo: str | None = None
    via_plantilla: bool = False

    def como_metadata(self) -> dict:
        datos: dict = {"transmitido": self.transmitido}
        if self.motivo:
            datos["motivo"] = self.motivo
        if self.via_plantilla:
            datos["plantilla"] = True
        return datos


async def enviar_al_ciudadano(
    canal: Canal,
    ciudadano: Ciudadano,
    texto: str,
    *,
    asunto: str | None = None,
    ultimo_entrante: datetime | None = None,
) -> ResultadoEnvio:
    """Transmite el texto al ciudadano por el canal de envío del caso.

    `asunto` es el del correo con el que se abrió el caso: se responde sobre él
    para que al ciudadano le quede en el mismo hilo y no como mensaje suelto.
    `ultimo_entrante` es el último mensaje que el ciudadano mandó por WhatsApp,
    que define si la ventana de 24 h está abierta.

    Fuera de la ventana, el texto sale dentro de la plantilla de seguimiento si
    hay una configurada; es el caso típico de quien solo llamó por teléfono y
    nunca escribió por WhatsApp.
    """
    if not texto.strip():
        return ResultadoEnvio(False, "texto_vacio")

    canal = canal_de_envio(canal)

    via_plantilla = False
    if canal == Canal.whatsapp and not dentro_de_ventana(ultimo_entrante):
        if not settings.whatsapp_plantilla_seguimiento:
            logger.warning("envio saliente: la ventana de 24 h de WhatsApp está cerrada")
            return ResultadoEnvio(False, "fuera_de_ventana")
        if len(whatsapp.parametro_de_plantilla(texto)) > whatsapp.MAX_PARAMETRO_PLANTILLA:
            logger.warning("envio saliente: la respuesta no entra en la plantilla de WhatsApp")
            return ResultadoEnvio(False, "texto_largo_para_plantilla")
        via_plantilla = True

    destino = ciudadano.email if canal == Canal.email else ciudadano.telefono
    if not destino:
        logger.warning("envio saliente: el ciudadano no tiene contacto para %s", canal.value)
        return ResultadoEnvio(False, "sin_contacto")

    try:
        if canal == Canal.email:
            await canal_email.enviar_mensaje(
                destino, texto, _asunto_respuesta(asunto)
            )
        elif via_plantilla:
            await whatsapp.enviar_plantilla(destino, texto)
        else:
            await whatsapp.enviar_mensaje(destino, texto)
    except Exception as error:
        logger.exception("envio saliente: falló el envío por %s", canal.value)
        return ResultadoEnvio(False, type(error).__name__)

    logger.info("envio saliente: respuesta del operador transmitida por %s", canal.value)
    return ResultadoEnvio(True, via_plantilla=via_plantilla)


async def responder_al_ciudadano(
    db: AsyncSession,
    *,
    canal: Canal,
    ciudadano: Ciudadano,
    texto: str,
    caso_id: uuid.UUID | None = None,
    asunto: str | None = None,
) -> ResultadoEnvio:
    """Transmite la respuesta automática del agente y la deja auditada.

    Los canales antes llamaban a `enviar_mensaje` directo, sin la red de
    `enviar_al_ciudadano`: un token vencido reventaba el webhook y una falla de
    SMTP quedaba solo en el log. La interacción ya está persistida en los dos
    casos, así que el ciudadano queda esperando algo que nunca salió y el
    operador no tiene cómo enterarse. Acá el fallo se audita y se sigue.

    Sin `caso_id` no hay a qué colgar la auditoría (un saludo no abre caso): se
    registra en el log y nada más.
    """
    resultado = await enviar_al_ciudadano(
        canal,
        ciudadano,
        texto,
        asunto=asunto,
        # Es la respuesta a un mensaje que el ciudadano acaba de mandar, así que
        # la ventana de 24 h de WhatsApp está abierta por definición.
        ultimo_entrante=datetime.now(timezone.utc),
    )

    if caso_id is not None:
        await registrar_auditoria(
            db,
            caso_id=caso_id,
            accion="envio_saliente",
            actor=ACTOR_AGENTE,
            actor_tipo=ActorInteraccion.agente_ia,
            metadata={"canal": canal.value, **resultado.como_metadata()},
        )
        await db.commit()
        if not resultado.transmitido and resultado.motivo != "texto_vacio":
            # RNF-02: el ciudadano no recibió la respuesta. El caso pasa a una
            # persona, que lo retoma por otro medio o cuando el canal vuelva.
            await escalar_caso_por_falla(db, caso_id, "falla_envio")
    elif not resultado.transmitido:
        logger.error(
            "envio saliente: no se pudo responder por %s y no hay caso que auditar (%s)",
            canal.value,
            resultado.motivo,
        )

    return resultado
