"""Teléfono web del panel: misma llamada que Twilio, con usuario del panel."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import telefono_web, webhooks
from app.main import app


@pytest.fixture
def cliente(mocker):
    atender = mocker.patch.object(telefono_web, "atender_stream", new=AsyncMock())
    return TestClient(app), atender


def _cierre(ws) -> int:
    with pytest.raises(WebSocketDisconnect) as cierre:
        ws.receive_json()
    return cierre.value.code


def test_sin_mensaje_de_autenticacion_se_corta(cliente):
    cliente_ws, atender = cliente
    with cliente_ws.websocket_connect("/api/telefono-web/stream") as ws:
        ws.send_json({"event": "start", "start": {"streamSid": "x"}})
        assert _cierre(ws) == 1008
    atender.assert_not_awaited()


def test_un_token_invalido_no_llama(cliente, mocker):
    cliente_ws, atender = cliente
    mocker.patch.object(telefono_web, "_usuario_del_token", new=AsyncMock(return_value=None))
    with cliente_ws.websocket_connect("/api/telefono-web/stream") as ws:
        ws.send_json({"event": "auth", "token": "x", "telefono": "+5491100000001"})
        assert _cierre(ws) == telefono_web.CIERRE_SIN_AUTORIZACION
    atender.assert_not_awaited()


def test_un_telefono_invalido_no_llama(cliente, mocker):
    cliente_ws, atender = cliente
    mocker.patch.object(telefono_web, "_usuario_del_token", new=AsyncMock(return_value=MagicMock()))
    with cliente_ws.websocket_connect("/api/telefono-web/stream") as ws:
        ws.send_json({"event": "auth", "token": "x", "telefono": "hola"})
        assert _cierre(ws) == telefono_web.CIERRE_TELEFONO_INVALIDO
    atender.assert_not_awaited()


def test_el_telefono_lo_fija_el_servidor(cliente, mocker):
    """El teléfono de la llamada es el que validó el servidor al autenticar,
    no uno que el navegador pueda mandar después en el `start`."""
    cliente_ws, atender = cliente
    mocker.patch.object(telefono_web, "_usuario_del_token", new=AsyncMock(return_value=MagicMock()))
    with cliente_ws.websocket_connect("/api/telefono-web/stream") as ws:
        ws.send_json({"event": "auth", "token": "x", "telefono": "54 9 11 0000-0001"})
        assert ws.receive_json() == {"event": "conectado"}
    atender.assert_awaited_once()
    assert atender.await_args.kwargs["telefono_fijo"] == "+5491100000001"


async def test_un_turno_avisa_estado_y_subtitulos(mocker):
    @asynccontextmanager
    async def sesion():
        yield MagicMock()

    mocker.patch.object(webhooks, "async_session_factory", sesion)
    mocker.patch.object(webhooks.voz, "transcribir", new=AsyncMock(return_value="Quiero un turno"))
    mocker.patch.object(
        webhooks.voz, "recibir_turno", new=AsyncMock(return_value={"respuesta": "¿Para qué día?"})
    )
    enviar = mocker.patch.object(webhooks.voz, "enviar_audio", new=AsyncMock())
    mocker.patch.object(webhooks.voz, "sintetizar_streaming", new=MagicMock())
    avisos = []

    async def avisar(evento):
        avisos.append(evento)

    await webhooks._procesar_turno_de_voz(MagicMock(), "sid", "+5491100000001", b"\xff" * 160, avisar)

    assert avisos == [
        {"event": "procesando"},
        {"event": "subtitulo", "quien": "ciudadano", "texto": "Quiero un turno"},
        {"event": "subtitulo", "quien": "agente", "texto": "¿Para qué día?"},
        {"event": "listo"},
    ]
    enviar.assert_awaited_once()


async def test_mientras_se_procesa_un_turno_se_sigue_leyendo_el_audio(mocker):
    """Antes el turno se procesaba dentro del bucle de lectura: el audio que
    seguía llegando llenaba la cola del servidor, que dejaba de leer el socket
    y cortaba la llamada por los pings sin respuesta."""
    import asyncio
    import base64

    habla = base64.b64encode(bytes([0x10]) * 160).decode()  # mu-law fuerte
    silencio = base64.b64encode(bytes([0xFF]) * 160).decode()
    mensajes = (
        [{"event": "start", "start": {"streamSid": "sid", "customParameters": {}}}]
        + [{"event": "media", "media": {"payload": habla}}] * 20
        + [{"event": "media", "media": {"payload": silencio}}] * 30
        # Llega mientras se procesa el turno: no arma otro.
        + [{"event": "media", "media": {"payload": habla}}] * 20
        + [{"event": "media", "media": {"payload": silencio}}] * 30
        + [{"event": "stop"}]
    )
    leidos = 0
    terminado = asyncio.Event()

    async def recibir():
        nonlocal leidos
        leidos += 1
        await asyncio.sleep(0)
        return mensajes[leidos - 1]

    async def turno_lento(*_args):
        await terminado.wait()

    websocket = MagicMock()
    websocket.receive_json = recibir
    mocker.patch.object(webhooks, "_saludar", new=AsyncMock())
    procesar = mocker.patch.object(webhooks, "_procesar_turno_de_voz", side_effect=turno_lento)

    await webhooks.atender_stream(websocket, telefono_fijo="+5491100000001")

    # Leyó todo, hasta el `stop`, sin esperar a que el turno terminara.
    assert leidos == len(mensajes)
    assert procesar.call_count == 1
    terminado.set()


async def test_si_no_se_entendio_nada_igual_avisa_que_termino(mocker):
    """Sin el "listo", la página quedaría mostrando "procesando" para siempre."""
    mocker.patch.object(webhooks.voz, "transcribir", new=AsyncMock(return_value="  "))
    avisos = []

    async def avisar(evento):
        avisos.append(evento)

    await webhooks._procesar_turno_de_voz(MagicMock(), "sid", "+5491100000001", b"\xff" * 160, avisar)

    assert avisos == [{"event": "procesando"}, {"event": "listo"}]
