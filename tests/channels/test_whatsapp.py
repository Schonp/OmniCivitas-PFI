import json
import uuid

import httpx
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.channels import whatsapp
from app.db.crud.ciudadanos import documento_provisorio
from app.db.models import ActorInteraccion, Canal, Caso, Interaccion, TipoCaso
from app.schemas.agente import ClasificacionIntent

TELEFONO = "+5491133334444"
WA_ID = "5491133334444"


def _payload(texto: str = "El poste no anda", *, tipo: str = "text", nombre: str = "Marta"):
    mensaje = {"from": WA_ID, "id": "wamid.ABC", "type": tipo}
    if tipo == "text":
        mensaje["text"] = {"body": texto}
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "0",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "contacts": [{"wa_id": WA_ID, "profile": {"name": nombre}}],
                            "messages": [mensaje],
                        },
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        (WA_ID, TELEFONO),          # Meta manda el wa_id sin el "+"
        (TELEFONO, TELEFONO),
        ("+54 9 11 3333-4444", TELEFONO),
        ("  whatsapp:+5491133334444  ", TELEFONO),
        # Así llega el mismo celular por una llamada de Twilio: sin el 9.
        ("+541133334444", TELEFONO),
        # Un número que no es argentino no se toca.
        ("+15551234567", "+15551234567"),
    ],
)
def test_normalizar_telefono_deja_formato_internacional(entrada, esperado):
    assert whatsapp.normalizar_telefono(entrada) == esperado


# --- Extracción del payload de Meta ----------------------------------------


def test_extraer_mensajes_toma_el_texto_y_el_nombre_de_perfil():
    mensajes = whatsapp.extraer_mensajes(_payload("Hay un pozo en Agüero"))

    assert len(mensajes) == 1
    assert mensajes[0].telefono == TELEFONO
    assert mensajes[0].texto == "Hay un pozo en Agüero"
    assert mensajes[0].nombre == "Marta"
    assert mensajes[0].id_externo == "wamid.ABC"


def test_extraer_mensajes_descarta_los_acuses_de_entrega():
    """El mismo webhook trae confirmaciones de entrega y lectura: no son
    mensajes del ciudadano y no deben entrar al grafo."""
    acuse = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {"statuses": [{"id": "wamid.X", "status": "delivered"}]},
                    }
                ]
            }
        ],
    }

    assert whatsapp.extraer_mensajes(acuse) == []


def test_extraer_mensajes_ignora_los_tipos_no_soportados():
    assert whatsapp.extraer_mensajes(_payload(tipo="audio")) == []


def test_extraer_mensajes_tolera_un_payload_vacio():
    assert whatsapp.extraer_mensajes({}) == []


# --- Seguridad del webhook -------------------------------------------------


def test_verificar_webhook_devuelve_el_desafio_con_el_token_correcto(mocker):
    mocker.patch.object(whatsapp.settings, "whatsapp_verify_token", "secreto")

    assert whatsapp.verificar_webhook("subscribe", "secreto", "12345") == "12345"
    assert whatsapp.verificar_webhook("subscribe", "otro", "12345") is None
    assert whatsapp.verificar_webhook("unsubscribe", "secreto", "12345") is None


def test_validar_firma_acepta_la_firma_correcta_y_rechaza_la_alterada(mocker):
    import hashlib
    import hmac

    mocker.patch.object(whatsapp.settings, "whatsapp_app_secret", "app-secret")
    cuerpo = b'{"hola":"mundo"}'
    firma = "sha256=" + hmac.new(b"app-secret", cuerpo, hashlib.sha256).hexdigest()

    assert whatsapp.validar_firma(cuerpo, firma) is True
    assert whatsapp.validar_firma(b'{"hola":"otro"}', firma) is False
    assert whatsapp.validar_firma(cuerpo, None) is False
    assert whatsapp.validar_firma(cuerpo, "sha256=deadbeef") is False


def test_sin_app_secret_solo_pasa_en_debug(mocker):
    mocker.patch.object(whatsapp.settings, "whatsapp_app_secret", "")
    mocker.patch.object(whatsapp.settings, "debug", True)
    assert whatsapp.validar_firma(b"{}", None) is True

    mocker.patch.object(whatsapp.settings, "debug", False)
    assert whatsapp.validar_firma(b"{}", None) is False


# --- Ciudadano y grafo -----------------------------------------------------


async def test_identificar_ciudadano_da_de_alta_en_primer_contacto(db_session):
    ciudadano = await whatsapp.identificar_ciudadano(db_session, TELEFONO, "Marta Ruiz")

    assert ciudadano.telefono == TELEFONO
    assert ciudadano.nombre == "Marta Ruiz"
    assert ciudadano.documento.startswith("SIN-DNI-")


async def test_identificar_ciudadano_reutiliza_el_telefono_existente(db_session):
    primero = await whatsapp.identificar_ciudadano(db_session, TELEFONO, "Marta Ruiz")
    segundo = await whatsapp.identificar_ciudadano(db_session, TELEFONO, "Otro Nombre")

    assert primero.id == segundo.id
    assert segundo.nombre == "Marta Ruiz"


def test_documento_provisorio_entra_en_la_columna():
    documento = documento_provisorio(TELEFONO)
    assert documento.startswith("SIN-DNI-")
    assert len(documento) <= 20


async def test_recibir_mensaje_crea_el_caso_con_canal_whatsapp(
    db_session, mock_llms, checkpointer_en_memoria
):
    mock_llms(
        ClasificacionIntent(
            intencion="reclamo", entidades={"categoria": "infraestructura"}, confianza=0.9
        ),
        respuestas_ejecutor=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "crear_reclamo",
                        "args": {
                            "descripcion": "El poste de luz está quemado",
                            "categoria": "servicio",
                        },
                        "id": "tc1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Registré su reclamo."),
        ],
    )

    final = await whatsapp.recibir_mensaje(
        db_session, telefono=WA_ID, mensaje="El poste no anda", nombre="Marta Ruiz"
    )

    caso = await db_session.get(Caso, uuid.UUID(final["caso_id"]))
    assert caso.tipo == TipoCaso.reclamo
    assert caso.canal_origen == Canal.whatsapp

    interacciones = (
        (await db_session.execute(select(Interaccion).where(Interaccion.caso_id == caso.id)))
        .scalars()
        .all()
    )
    assert {i.canal for i in interacciones} == {Canal.whatsapp}
    assert {i.actor for i in interacciones} == {
        ActorInteraccion.ciudadano,
        ActorInteraccion.agente_ia,
    }


# --- Envío -----------------------------------------------------------------


async def test_enviar_mensaje_postea_a_la_api_de_meta(mocker):
    mocker.patch.object(whatsapp.settings, "whatsapp_phone_number_id", "123456")
    mocker.patch.object(whatsapp.settings, "whatsapp_access_token", "token-secreto")
    mocker.patch.object(whatsapp.settings, "whatsapp_api_version", "v21.0")

    capturado = {}

    def responder(request: httpx.Request) -> httpx.Response:
        capturado["url"] = str(request.url)
        capturado["auth"] = request.headers.get("Authorization")
        capturado["body"] = request.content
        return httpx.Response(200, json={"messages": [{"id": "wamid.ENVIADO"}]})

    transporte = httpx.MockTransport(responder)
    original = httpx.AsyncClient

    def cliente(*args, **kwargs):
        kwargs["transport"] = transporte
        return original(*args, **kwargs)

    mocker.patch.object(whatsapp.httpx, "AsyncClient", cliente)

    identificador = await whatsapp.enviar_mensaje(TELEFONO, "Su reclamo quedó registrado.")

    assert identificador == "wamid.ENVIADO"
    assert capturado["url"] == "https://graph.facebook.com/v21.0/123456/messages"
    assert capturado["auth"] == "Bearer token-secreto"
    enviado = json.loads(capturado["body"])
    # Sin el "+" y, por ser argentino, sin el 9 que sí trae el wa_id.
    assert enviado["to"] == "541133334444"
    assert enviado["messaging_product"] == "whatsapp"
    assert enviado["text"]["body"] == "Su reclamo quedó registrado."


async def test_enviar_mensaje_ignora_texto_vacio(mocker):
    llamado = mocker.patch.object(whatsapp.httpx, "AsyncClient")

    assert await whatsapp.enviar_mensaje(TELEFONO, "   ") is None
    llamado.assert_not_called()


async def test_enviar_mensaje_exige_credenciales(mocker):
    mocker.patch.object(whatsapp.settings, "whatsapp_phone_number_id", "")

    with pytest.raises(RuntimeError, match="Faltan credenciales"):
        await whatsapp.enviar_mensaje(TELEFONO, "hola")


async def test_enviar_plantilla_postea_el_texto_como_parametro(mocker):
    mocker.patch.object(whatsapp.settings, "whatsapp_phone_number_id", "123456")
    mocker.patch.object(whatsapp.settings, "whatsapp_access_token", "token-secreto")
    mocker.patch.object(whatsapp.settings, "whatsapp_plantilla_seguimiento", "seguimiento_caso")
    mocker.patch.object(whatsapp.settings, "whatsapp_plantilla_idioma", "es_AR")

    capturado = {}

    def responder(request: httpx.Request) -> httpx.Response:
        capturado["body"] = request.content
        return httpx.Response(200, json={"messages": [{"id": "wamid.PLANTILLA"}]})

    transporte = httpx.MockTransport(responder)
    original = httpx.AsyncClient

    def cliente(*args, **kwargs):
        kwargs["transport"] = transporte
        return original(*args, **kwargs)

    mocker.patch.object(whatsapp.httpx, "AsyncClient", cliente)

    identificador = await whatsapp.enviar_plantilla(
        TELEFONO, "Su reclamo quedó registrado.\n\nLo contactamos."
    )

    assert identificador == "wamid.PLANTILLA"
    enviado = json.loads(capturado["body"])
    assert enviado["to"] == "541133334444"
    assert enviado["type"] == "template"
    assert enviado["template"]["name"] == "seguimiento_caso"
    assert enviado["template"]["language"] == {"code": "es_AR"}
    # Meta rechaza parámetros con saltos de línea: el texto va en una sola línea.
    assert enviado["template"]["components"] == [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "Su reclamo quedó registrado. Lo contactamos."}
            ],
        }
    ]


async def test_enviar_plantilla_exige_una_plantilla_configurada(mocker):
    mocker.patch.object(whatsapp.settings, "whatsapp_plantilla_seguimiento", "")

    with pytest.raises(RuntimeError, match="plantilla"):
        await whatsapp.enviar_plantilla(TELEFONO, "hola")


def test_parametro_de_plantilla_colapsa_espacios_y_saltos():
    assert whatsapp.parametro_de_plantilla("  Hola\n\tvecina,     ya   está. ") == (
        "Hola vecina, ya está."
    )


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        # El wa_id argentino trae un 9 que la API de envío no acepta.
        ("+5491155550123", "541155550123"),
        ("5491155550123", "541155550123"),
        ("+541155550123", "541155550123"),
        # Otros países no se tocan.
        ("+5511999998888", "5511999998888"),
        ("+14155238886", "14155238886"),
    ],
)
def test_destino_para_meta_quita_el_9_argentino(entrada, esperado):
    assert whatsapp.destino_para_meta(entrada) == esperado
