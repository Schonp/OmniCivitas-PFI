"""Canal WhatsApp sobre la Cloud API de Meta.

Cumple el mismo contrato que los demás canales: normaliza al ciudadano y su
identificador, delega en el orquestador y transmite la respuesta. La
continuidad la resuelve el grafo a partir de `canal + identificador`; acá el
identificador es el teléfono, que `contexto.obtener_ciudadano_por_canal`
busca por hash.

Se habla con Meta directamente en vez de con un proveedor intermediario: es la
misma plataforma que revenden los proveedores comerciales, sin el margen ni el
tercero de por medio, lo que además es coherente con no delegar el
procesamiento de las interacciones ciudadanas.

**Ventana de 24 horas.** WhatsApp solo admite mensajes libres dentro de las 24
horas posteriores al último mensaje del ciudadano; fuera de esa ventana hay que
usar una plantilla aprobada por Meta. Es una regla de la plataforma, no del
proveedor. `salida.enviar_al_ciudadano` usa la plantilla de seguimiento si hay
una configurada, y si no, no intenta el envío, para que el operador se entere
por la auditoría en vez de que el mensaje se pierda.
"""

import hashlib
import hmac
import logging
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import procesar_mensaje
from app.agents.state import AgentState
from app.core.config import settings
from app.db.crud.ciudadanos import (
    alta_por_contacto,
    documento_provisorio,
    obtener_ciudadano_por_telefono,
)
from app.db.models import Canal, Ciudadano
from app.schemas.ciudadano import CiudadanoCreate

logger = logging.getLogger(__name__)

CANAL = Canal.whatsapp
NOMBRE_POR_DEFECTO = "Ciudadano sin identificar"
API_BASE = "https://graph.facebook.com"
TIMEOUT = 20.0
VENTANA_HORAS = 24
# Meta limita el cuerpo de una plantilla a 1024 caracteres contando el texto
# fijo; con este margen entra la respuesta del operador junto al encabezado.
MAX_PARAMETRO_PLANTILLA = 900


@dataclass(frozen=True)
class MensajeEntrante:
    """Un mensaje de WhatsApp ya extraído del payload de Meta."""

    telefono: str
    nombre: str | None
    texto: str
    id_externo: str


def normalizar_telefono(valor: str) -> str:
    """Meta identifica al ciudadano por `wa_id`, que viene sin el `+` inicial
    (`5491133334444`). El teléfono se guarda en formato internacional para que
    el mismo ciudadano se resuelva igual si mañana llega por voz."""
    numero = valor.strip().replace(" ", "").replace("-", "")
    if numero.startswith("whatsapp:"):
        numero = numero[len("whatsapp:") :]
    if numero and not numero.startswith("+"):
        numero = "+" + numero
    # Un celular argentino llega con dos formas según el canal: WhatsApp lo
    # manda con el 9 (+54 9 11 5555 0123) y la telefonía, sin él (+54 11 5555
    # 0123). Sin unificarlos, el vecino que escribió por WhatsApp y después
    # llama no se reconoce como el mismo: se le piden los datos de nuevo y la
    # continuidad entre canales se corta. Se guarda siempre con el 9.
    if numero.startswith("+54") and not numero.startswith("+549") and len(numero) == len("+54") + 10:
        numero = "+549" + numero[len("+54"):]
    return numero


# --- Entrada: webhook de Meta ----------------------------------------------


def verificar_webhook(modo: str | None, token: str | None, desafio: str | None) -> str | None:
    """Handshake de alta del webhook: Meta pega un GET con un token propio y
    espera que le devuelvan el desafío tal cual. Devuelve None si no valida."""
    if modo == "subscribe" and token and token == settings.whatsapp_verify_token:
        return desafio
    logger.warning("webhook whatsapp: verificación rechazada")
    return None


def validar_firma(cuerpo: bytes, firma: str | None) -> bool:
    """Valida `X-Hub-Signature-256` sobre el cuerpo crudo.

    Sin esto cualquiera podría postear mensajes falsos al endpoint y hacerlos
    pasar por un ciudadano. En desarrollo, si no hay app secret configurado, se
    deja pasar para poder probar sin credenciales.
    """
    if not settings.whatsapp_app_secret:
        logger.warning("canal whatsapp: sin WHATSAPP_APP_SECRET, no se valida la firma")
        return settings.debug
    if not firma or not firma.startswith("sha256="):
        return False
    esperada = hmac.new(
        settings.whatsapp_app_secret.encode(), cuerpo, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(esperada, firma[len("sha256=") :])


def extraer_mensajes(payload: dict) -> list[MensajeEntrante]:
    """Saca los mensajes de texto del payload anidado de Meta.

    El mismo webhook recibe además acuses de entrega y de lectura en
    `statuses`, que no son mensajes del ciudadano y se descartan. Los tipos que
    no son texto (audio, imagen, ubicación) quedan fuera del alcance.
    """
    mensajes: list[MensajeEntrante] = []
    for entrada in payload.get("entry") or []:
        for cambio in entrada.get("changes") or []:
            valor = cambio.get("value") or {}
            nombres = {
                c.get("wa_id"): (c.get("profile") or {}).get("name")
                for c in valor.get("contacts") or []
            }
            for mensaje in valor.get("messages") or []:
                if mensaje.get("type") != "text":
                    logger.info(
                        "canal whatsapp: se ignora un mensaje de tipo %s", mensaje.get("type")
                    )
                    continue
                texto = ((mensaje.get("text") or {}).get("body") or "").strip()
                origen = mensaje.get("from")
                if not texto or not origen:
                    continue
                mensajes.append(
                    MensajeEntrante(
                        telefono=normalizar_telefono(origen),
                        nombre=nombres.get(origen),
                        texto=texto,
                        id_externo=mensaje.get("id") or "",
                    )
                )
    return mensajes


# --- Ciudadano y orquestador -----------------------------------------------


async def identificar_ciudadano(
    db: AsyncSession, telefono: str, nombre: str | None = None
) -> Ciudadano:
    """Busca por teléfono y, si es el primer contacto, da de alta al ciudadano."""
    ciudadano = await obtener_ciudadano_por_telefono(db, telefono)
    if ciudadano is not None:
        return ciudadano

    logger.info("canal whatsapp: alta de ciudadano por primer contacto")
    return await alta_por_contacto(
        db,
        CiudadanoCreate(
            documento=documento_provisorio(telefono),
            nombre=(nombre or NOMBRE_POR_DEFECTO).strip()[:200],
            telefono=telefono,
        ),
    )


async def recibir_mensaje(
    db: AsyncSession, *, telefono: str, mensaje: str, nombre: str | None = None
) -> AgentState:
    """Punto de entrada del canal: normaliza, asegura el ciudadano y corre el grafo."""
    numero = normalizar_telefono(telefono)
    await identificar_ciudadano(db, numero, nombre)
    logger.debug("canal whatsapp: mensaje entrante")
    return await procesar_mensaje(
        db,
        mensaje=mensaje,
        canal=CANAL,
        identificador=numero,
    )


# --- Salida ----------------------------------------------------------------


def destino_para_meta(telefono: str) -> str:
    """Adapta el número al formato que acepta la API de envío.

    WhatsApp identifica a los celulares argentinos con un 9 después del código
    de país (`549 11 ...`), y así llega el `wa_id` en el webhook. Pero la API de
    envío espera el número sin ese 9 (`54 11 ...`): mandarle el wa_id tal cual
    devuelve 131030 "Recipient phone number not in allowed list", que despista
    porque suena a un problema de permisos y es de formato.
    """
    numero = normalizar_telefono(telefono).lstrip("+")
    if numero.startswith("549") and len(numero) > 3:
        numero = "54" + numero[3:]
    return numero


def parametro_de_plantilla(texto: str) -> str:
    """Meta rechaza los parámetros de plantilla con saltos de línea, tabulaciones
    o más de cuatro espacios seguidos, así que el texto del operador se pasa a
    una sola línea antes de enviarlo."""
    return " ".join(texto.split())


async def enviar_mensaje(telefono: str, texto: str) -> str | None:
    """Envía la respuesta por WhatsApp. Devuelve el id del mensaje en Meta."""
    if not texto.strip():
        return None
    return await _postear(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": destino_para_meta(telefono),
            "type": "text",
            "text": {"preview_url": False, "body": texto},
        }
    )


async def enviar_plantilla(telefono: str, texto: str) -> str | None:
    """Envía el texto dentro de la plantilla de seguimiento aprobada por Meta.

    Es la única forma de escribirle a un ciudadano fuera de la ventana de 24
    horas, por ejemplo a quien solo llamó por teléfono y nunca escribió por
    WhatsApp. La plantilla tiene que tener exactamente un parámetro en el cuerpo
    (`{{1}}`), donde va el texto del operador.
    """
    parametro = parametro_de_plantilla(texto)
    if not parametro:
        return None
    if not settings.whatsapp_plantilla_seguimiento:
        raise RuntimeError(
            "Falta la plantilla de seguimiento: definir WHATSAPP_PLANTILLA_SEGUIMIENTO"
        )
    return await _postear(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": destino_para_meta(telefono),
            "type": "template",
            "template": {
                "name": settings.whatsapp_plantilla_seguimiento,
                "language": {"code": settings.whatsapp_plantilla_idioma},
                "components": [
                    {"type": "body", "parameters": [{"type": "text", "text": parametro}]}
                ],
            },
        }
    )


async def _postear(cuerpo: dict) -> str | None:
    """Manda el mensaje a la API de Meta. Devuelve el id del mensaje enviado."""
    if not settings.whatsapp_phone_number_id or not settings.whatsapp_access_token:
        raise RuntimeError(
            "Faltan credenciales de WhatsApp: definir WHATSAPP_PHONE_NUMBER_ID "
            "y WHATSAPP_ACCESS_TOKEN"
        )

    url = (
        f"{API_BASE}/{settings.whatsapp_api_version}"
        f"/{settings.whatsapp_phone_number_id}/messages"
    )

    async with httpx.AsyncClient(timeout=TIMEOUT) as cliente:
        respuesta = await cliente.post(
            url,
            json=cuerpo,
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
        )
        if respuesta.status_code >= 400:
            # raise_for_status no incluye el cuerpo, y el motivo real de Meta
            # viene ahí: sin esto un fallo de envío no deja rastro accionable.
            logger.error(
                "canal whatsapp: Meta rechazó el envío (%s): %s",
                respuesta.status_code,
                respuesta.text[:500],
            )
        respuesta.raise_for_status()
        datos = respuesta.json()

    identificador = (datos.get("messages") or [{}])[0].get("id")
    logger.info("canal whatsapp: respuesta enviada id=%s", identificador)
    return identificador
