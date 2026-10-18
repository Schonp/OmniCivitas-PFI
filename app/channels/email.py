"""Canal de correo electrónico sobre IMAP/SMTP.

Mismo contrato que los demás canales: normaliza al ciudadano y su identificador,
delega en el orquestador y transmite la respuesta. Acá el identificador es la
dirección de correo, que `contexto.obtener_ciudadano_por_canal` busca por hash.

A diferencia de WhatsApp no hay webhook: el correo se consulta por polling del
buzón, así que no hace falta exponer la aplicación a internet. Se usa la
biblioteca estándar (imaplib/smtplib) corrida en un thread, para no agregar
dependencias al proyecto.
"""

import asyncio
import email as email_lib
import uuid
import imaplib
import logging
import smtplib
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import procesar_mensaje
from app.agents.state import AgentState
from app.core.config import settings
from app.db.crud.ciudadanos import (
    crear_ciudadano,
    documento_provisorio,
    obtener_ciudadano_por_email,
)
from app.db.models import Canal, Caso, Ciudadano
from app.schemas.ciudadano import CiudadanoCreate

logger = logging.getLogger(__name__)

CANAL = Canal.email
NOMBRE_POR_DEFECTO = "Ciudadano sin identificar"
ASUNTO_RESPUESTA = "Re: su consulta al organismo"
CUERPO_MAX = 4000


@dataclass(frozen=True)
class CorreoEntrante:
    """Un correo ya normalizado, listo para entrar al orquestador."""

    remitente: str
    nombre: str | None
    asunto: str
    cuerpo: str


def _texto_plano(mensaje: email_lib.message.Message) -> str:
    """Extrae el cuerpo en texto plano, ignorando adjuntos y la parte HTML."""
    if not mensaje.is_multipart():
        carga = mensaje.get_payload(decode=True) or b""
        return carga.decode(mensaje.get_content_charset() or "utf-8", errors="replace")

    for parte in mensaje.walk():
        if parte.get_content_type() != "text/plain":
            continue
        if "attachment" in str(parte.get("Content-Disposition", "")):
            continue
        carga = parte.get_payload(decode=True) or b""
        return carga.decode(parte.get_content_charset() or "utf-8", errors="replace")
    return ""


def _decodificar(valor: str | None) -> str:
    if not valor:
        return ""
    return str(make_header(decode_header(valor)))


def _quitar_citas(cuerpo: str) -> str:
    """Se queda con lo que el ciudadano escribió ahora: corta en la primera
    línea citada o en el encabezado de respuesta, para no reenviarle al agente
    toda la conversación anterior (que además ya tiene en el historial)."""
    lineas: list[str] = []
    for linea in cuerpo.splitlines():
        limpia = linea.strip()
        if limpia.startswith(">") or limpia.startswith("-----"):
            break
        if limpia.startswith("El ") and limpia.endswith("escribió:"):
            break
        lineas.append(linea)
    return "\n".join(lineas).strip()[:CUERPO_MAX]




async def identificar_ciudadano(
    db: AsyncSession, direccion: str, nombre: str | None = None
) -> Ciudadano:
    ciudadano = await obtener_ciudadano_por_email(db, direccion)
    if ciudadano is not None:
        return ciudadano

    logger.info("canal email: alta de ciudadano por primer contacto")
    return await crear_ciudadano(
        db,
        CiudadanoCreate(
            documento=documento_provisorio(direccion),
            nombre=(nombre or NOMBRE_POR_DEFECTO).strip()[:200],
            email=direccion,
        ),
    )


async def recibir_mensaje(
    db: AsyncSession, *, direccion: str, mensaje: str, nombre: str | None = None
) -> AgentState:
    """Punto de entrada del canal: asegura el ciudadano y corre el grafo."""
    remitente = direccion.strip().lower()
    await identificar_ciudadano(db, remitente, nombre)
    logger.debug("canal email: mensaje entrante")
    return await procesar_mensaje(
        db,
        mensaje=mensaje,
        canal=CANAL,
        identificador=remitente,
    )


# --- Infraestructura IMAP/SMTP (síncrona, se corre en thread) ---------------


def _leer_no_leidos() -> list[CorreoEntrante]:
    """Trae los correos sin leer del buzón y los marca como leídos."""
    if not settings.imap_host or not settings.imap_user:
        raise RuntimeError("Faltan credenciales IMAP: definir IMAP_HOST e IMAP_USER")

    correos: list[CorreoEntrante] = []
    with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port) as buzon:
        buzon.login(settings.imap_user, settings.imap_password)
        buzon.select("INBOX")
        estado, datos = buzon.search(None, "UNSEEN")
        if estado != "OK":
            return correos

        for uid in datos[0].split():
            estado, crudo = buzon.fetch(uid, "(RFC822)")
            if estado != "OK" or not crudo or not isinstance(crudo[0], tuple):
                continue
            mensaje = email_lib.message_from_bytes(crudo[0][1])
            nombre, direccion = parseaddr(mensaje.get("From", ""))
            if not direccion:
                continue
            # Nunca contestarse a sí mismo: si la casilla recibe su propia
            # respuesta (o el ciudadano tiene un autorespondedor), agente y
            # autorespondedor se contestarían en bucle indefinidamente.
            if direccion.lower() == settings.imap_user.lower():
                logger.warning("canal email: se ignora un correo de la propia casilla")
                continue
            cuerpo = _quitar_citas(_texto_plano(mensaje))
            if not cuerpo:
                continue
            correos.append(
                CorreoEntrante(
                    remitente=direccion.lower(),
                    nombre=_decodificar(nombre) or None,
                    asunto=_decodificar(mensaje.get("Subject")),
                    cuerpo=cuerpo,
                )
            )
            buzon.store(uid, "+FLAGS", "\\Seen")
    return correos


async def consultar_buzon() -> list[CorreoEntrante]:
    """Versión async de la lectura del buzón."""
    return await asyncio.to_thread(_leer_no_leidos)


def _enviar_sync(destino: str, texto: str, asunto: str) -> None:
    if not settings.smtp_host or not settings.smtp_user:
        raise RuntimeError("Faltan credenciales SMTP: definir SMTP_HOST y SMTP_USER")

    mensaje = EmailMessage()
    mensaje["From"] = settings.smtp_user
    mensaje["To"] = destino
    mensaje["Subject"] = asunto
    mensaje.set_content(texto)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as servidor:
        servidor.starttls()
        servidor.login(settings.smtp_user, settings.smtp_password)
        servidor.send_message(mensaje)


async def enviar_mensaje(destino: str, texto: str, asunto: str = ASUNTO_RESPUESTA) -> None:
    """Envía la respuesta del agente por correo."""
    if not texto.strip():
        return
    await asyncio.to_thread(_enviar_sync, destino, texto, asunto)
    logger.info("canal email: respuesta enviada")


async def _guardar_asunto(db: AsyncSession, caso_id: str | None, asunto: str) -> None:
    """Deja el asunto del primer correo en el caso, para que el operador pueda
    responder sobre el mismo hilo. No lo pisa si ya estaba."""
    if not caso_id or not asunto:
        return
    caso = await db.get(Caso, uuid.UUID(caso_id))
    if caso is not None and not caso.asunto:
        caso.asunto = asunto[:300]
        await db.commit()


async def procesar_buzon(db: AsyncSession) -> int:
    """Ciclo completo del canal: lee lo no leído, lo pasa por el grafo y
    responde. Devuelve cuántos correos se procesaron."""
    correos = await consultar_buzon()
    for correo in correos:
        try:
            final = await recibir_mensaje(
                db,
                direccion=correo.remitente,
                mensaje=correo.cuerpo,
                nombre=correo.nombre,
            )
            await _guardar_asunto(db, final.get("caso_id"), correo.asunto)
            respuesta = final.get("respuesta")
            if respuesta:
                # Import local: salida importa este modulo para poder enviar por
                # correo, asi que a nivel de modulo seria un ciclo.
                from app.channels import salida

                ciudadano = await obtener_ciudadano_por_email(db, correo.remitente)
                if ciudadano is not None:
                    caso_id = final.get("caso_id")
                    await salida.responder_al_ciudadano(
                        db,
                        canal=CANAL,
                        ciudadano=ciudadano,
                        texto=respuesta,
                        caso_id=uuid.UUID(caso_id) if caso_id else None,
                        asunto=correo.asunto,
                    )
        except Exception:
            logger.exception("canal email: falló el procesamiento de un correo")
    return len(correos)
