import audioop
import base64
import uuid
import wave
from io import BytesIO

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.channels import voz
from app.db.crud.ciudadanos import documento_provisorio
from app.db.models import Canal, Caso, Interaccion, TipoCaso
from app.schemas.agente import ClasificacionIntent

TELEFONO = "+5491133334444"


def _tono_mulaw(frecuencia: int = 440, ms: int = 20, amplitud: int = 12000) -> bytes:
    """Un chunk mulaw de `ms` milisegundos a 8kHz que simula una voz (energía
    alta). Mismo tamaño que manda Twilio por chunk (160 bytes para 20ms)."""
    import math

    n = int(voz.SAMPLE_RATE_TWILIO * ms / 1000)
    pcm = b"".join(
        int(amplitud * math.sin(2 * math.pi * frecuencia * i / voz.SAMPLE_RATE_TWILIO)).to_bytes(
            2, "little", signed=True
        )
        for i in range(n)
    )
    return audioop.lin2ulaw(pcm, voz.ANCHO_MUESTRA_PCM)


def _silencio_mulaw(ms: int = 20) -> bytes:
    n = int(voz.SAMPLE_RATE_TWILIO * ms / 1000)
    pcm = b"\x00\x00" * n
    return audioop.lin2ulaw(pcm, voz.ANCHO_MUESTRA_PCM)


# --- Conversión de audio -----------------------------------------------------


def test_mulaw_a_wav_produce_un_wav_valido_al_sample_rate_de_twilio():
    mulaw = _tono_mulaw()
    wav_bytes = voz.mulaw_a_wav(mulaw)

    with wave.open(BytesIO(wav_bytes), "rb") as w:
        assert w.getframerate() == voz.SAMPLE_RATE_TWILIO
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() == len(audioop.ulaw2lin(mulaw, 2)) // 2


async def test_enviar_audio_resamplea_el_stream_de_kokoro_a_mensajes_de_twilio(mocker):
    # Kokoro entrega PCM16 24kHz en pedazos; acá simulamos dos pedazos de
    # silencio que entre los dos suman 100ms a esa frecuencia.
    async def pcm_24k_stream():
        mitad = b"\x00\x00" * int(voz.SAMPLE_RATE_KOKORO * 0.05)
        yield mitad
        yield mitad

    websocket = mocker.AsyncMock()
    await voz.enviar_audio(websocket, "MZ123", pcm_24k_stream())

    mensajes = [llamada.args[0] for llamada in websocket.send_json.call_args_list]
    mensajes_media = [m for m in mensajes if m["event"] == "media"]

    # 100ms a 8kHz mulaw (1 byte/muestra) = 800 bytes = 5 chunks de 160 bytes.
    assert len(mensajes_media) == 5
    assert all(len(base64.b64decode(m["media"]["payload"])) == 160 for m in mensajes_media)
    assert all(m["streamSid"] == "MZ123" for m in mensajes_media)
    assert mensajes[-1] == {
        "event": "mark",
        "streamSid": "MZ123",
        "mark": {"name": "fin_respuesta"},
    }


async def test_enviar_audio_soporta_chunks_cortados_en_un_byte_impar(mocker):
    """El stream HTTP corta en cualquier punto, no en los límites de 2
    bytes/muestra con que `sintetizar_streaming` yieldea -- un chunk con un
    largo impar hacía reventar `audioop.ratecv` con "not a whole number of
    frames" en la primera llamada real (ver DEVLOG.md)."""
    pcm_100ms = b"\x00\x00" * int(voz.SAMPLE_RATE_KOKORO * 0.1)

    async def pcm_24k_stream_cortado_feo():
        yield pcm_100ms[:1]
        yield pcm_100ms[1:1201]
        yield pcm_100ms[1201:]

    websocket = mocker.AsyncMock()
    await voz.enviar_audio(websocket, "MZ123", pcm_24k_stream_cortado_feo())

    mensajes_media = [
        m for m in (c.args[0] for c in websocket.send_json.call_args_list) if m["event"] == "media"
    ]
    assert len(mensajes_media) == 5
    assert all(len(base64.b64decode(m["media"]["payload"])) == 160 for m in mensajes_media)


# --- Detector de turno por energía ------------------------------------------


def test_detector_de_turno_no_dispara_con_silencio_puro():
    detector = voz.DetectorDeTurno()
    for _ in range(50):
        assert detector.agregar_chunk(_silencio_mulaw()) is False


def test_detector_de_turno_dispara_tras_habla_y_silencio_sostenido():
    detector = voz.DetectorDeTurno()

    # Habla: no dispara mientras sigue hablando.
    for _ in range(voz.CHUNKS_MINIMOS_HABLA):
        assert detector.agregar_chunk(_tono_mulaw()) is False

    # Silencio corto: todavía no alcanza para cerrar el turno.
    for _ in range(voz.CHUNKS_SILENCIO_FIN_TURNO - 1):
        assert detector.agregar_chunk(_silencio_mulaw()) is False

    # Un chunk más de silencio cierra el turno.
    assert detector.agregar_chunk(_silencio_mulaw()) is True

    turno = detector.tomar_turno()
    assert len(turno) > 0

    # Se resetea: el siguiente silencio puro no vuelve a disparar.
    assert detector.agregar_chunk(_silencio_mulaw()) is False


def test_detector_de_turno_no_dispara_con_habla_corta_antes_del_minimo():
    detector = voz.DetectorDeTurno()
    for _ in range(voz.CHUNKS_MINIMOS_HABLA - 1):
        detector.agregar_chunk(_tono_mulaw())

    for _ in range(voz.CHUNKS_SILENCIO_FIN_TURNO + 5):
        assert detector.agregar_chunk(_silencio_mulaw()) is False


# --- TwiML y firma -----------------------------------------------------------


def test_twiml_conectar_stream_incluye_la_url_y_el_telefono(mocker):
    mocker.patch.object(voz.settings, "voz_websocket_url", "wss://ejemplo.com/stream")

    xml = voz.twiml_conectar_stream(TELEFONO)

    assert "<Connect><Stream" in xml
    assert 'url="wss://ejemplo.com/stream"' in xml
    assert f'value="{TELEFONO}"' in xml
    assert 'name="telefono"' in xml


def test_validar_firma_sin_auth_token_solo_pasa_en_debug(mocker):
    mocker.patch.object(voz.settings, "twilio_auth_token", "")
    mocker.patch.object(voz.settings, "debug", True)
    assert voz.validar_firma("https://x", {}, None) is True

    mocker.patch.object(voz.settings, "debug", False)
    assert voz.validar_firma("https://x", {}, None) is False


def test_validar_firma_delega_en_el_validador_oficial_de_twilio(mocker):
    mocker.patch.object(voz.settings, "twilio_auth_token", "un-auth-token")
    mock_validate = mocker.patch(
        "app.channels.voz.RequestValidator.validate", return_value=True
    )

    resultado = voz.validar_firma("https://x/voz", {"From": TELEFONO}, "firma-cualquiera")

    assert resultado is True
    mock_validate.assert_called_once_with("https://x/voz", {"From": TELEFONO}, "firma-cualquiera")


def test_validar_firma_sin_firma_rechaza_sin_llamar_al_validador(mocker):
    mocker.patch.object(voz.settings, "twilio_auth_token", "un-auth-token")
    mock_validate = mocker.patch("app.channels.voz.RequestValidator.validate")

    assert voz.validar_firma("https://x", {}, None) is False
    mock_validate.assert_not_called()


# --- Ciudadano y grafo -------------------------------------------------------


async def test_identificar_ciudadano_da_de_alta_en_primer_contacto(db_session):
    ciudadano = await voz.identificar_ciudadano(db_session, TELEFONO)

    assert ciudadano.telefono == TELEFONO
    assert ciudadano.documento.startswith("SIN-DNI-")


async def test_saludo_inicial_saluda_sin_menu_y_sin_pasar_por_el_grafo(db_session):
    """La IA habla primero: no hay un "hola" del ciudadano todavía con qué
    clasificar una intención, así que esto arma el saludo directo en vez de
    pasar por `procesar_mensaje`."""
    saludo = await voz.saludo_inicial(db_session, TELEFONO)

    assert "asistente virtual" in saludo
    assert "1." not in saludo


@pytest.mark.parametrize(
    "transcripcion,esperado",
    [
        # Así transcribe Whisper large-v3-turbo un DNI dictado con pausas o de a pares.
        ("3012-3456", "30123456"),
        ("Mi DNI es 3 0 1 2 3 4 5 6.", "Mi DNI es 30123456."),
        ("Mi DNI es 30 12 34 56", "Mi DNI es 30123456"),
        ("tres cero uno dos tres cuatro cinco seis", "30123456"),
        ("Mi nombre es Pedro y mi DNI es 30-123-456.", "Mi nombre es Pedro y mi DNI es 30123456."),
        ("Siete millones: 7 123 456", "Siete millones: 7123456"),
    ],
)
def test_un_dni_dictado_de_a_digitos_se_une_en_un_solo_numero(transcripcion, esperado):
    assert voz.unir_dni_dictado(transcripcion) == esperado


@pytest.mark.parametrize(
    "transcripcion",
    [
        "La dirección es Guatemala 4100.",
        "Corrientes 1234, 5 B",
        "Puede ser a las 10 30?",
        "Mi teléfono es 11 4444 5555",
        "Tengo dos o tres reclamos",
        "Uno de los faroles, dos cuadras más allá",
    ],
)
def test_lo_que_no_tiene_largo_de_dni_queda_igual(transcripcion):
    assert voz.unir_dni_dictado(transcripcion) == transcripcion


@pytest.mark.parametrize(
    "transcripcion,esperado",
    [
        # Así transcribe Whisper large-v3-turbo un apellido deletreado.
        ("Mi nombre es Pedro, S-C-H-O-N.", "Mi nombre es Pedro Schon."),
        ("Mi nombre es Pedro Schón, se escribe S-C-H-O-N.", "Mi nombre es Pedro Schon."),
        ("Mi nombre es Laura, J-I-M-E-N-E-Z y mi DNI es 30123456.",
         "Mi nombre es Laura Jimenez y mi DNI es 30123456."),
        ("S C H O N", "Schon"),
    ],
)
def test_un_apellido_deletreado_se_escribe_como_palabra(transcripcion, esperado):
    assert voz.unir_apellido_deletreado(transcripcion) == esperado


@pytest.mark.parametrize(
    "transcripcion",
    [
        "Mi nombre es Pedro y mi DNI es 30123456.",
        "Y a la tarde pasa el camión",
        "Vivo en Corrientes 1234, 5 B",
    ],
)
def test_sin_deletreo_el_texto_queda_igual(transcripcion):
    assert voz.unir_apellido_deletreado(transcripcion) == transcripcion


def test_una_sigla_deletreada_se_escribe_junta_y_no_como_apellido():
    assert voz.unir_apellido_deletreado("Mi D-N-I es 30123456") == "Mi DNI es 30123456"


def test_el_nombre_deletreado_llega_a_la_identidad():
    """De punta a punta: lo que transcribe Whisper, normalizado, es lo que la
    regla de identidad necesita para registrar nombre, apellido y DNI."""
    from app.agents.identidad import extraer_identidad

    texto = voz.normalizar_dictado("Mi nombre es Pedro, S-C-H-O-N, y mi DNI es 3012-3456.")

    assert extraer_identidad(texto) == ("Pedro Schon", "30123456")


async def test_el_saludo_de_la_llamada_lleva_todos_los_avisos_de_una_vez(db_session):
    """Primer contacto: el saludo dice que habla una IA, que puede pedir una
    persona y qué datos se guardan, todo junto y antes de la pregunta."""
    from app.agents.aviso_ia import AVISO_DATOS_VOZ

    saludo = await voz.saludo_inicial(db_session, TELEFONO)

    assert "inteligencia artificial" in saludo
    assert "persona" in saludo
    assert AVISO_DATOS_VOZ in saludo
    assert saludo.endswith("?")


async def test_el_primer_turno_de_la_llamada_no_repite_los_avisos(
    db_session, mock_llms, checkpointer_en_memoria
):
    """Los avisos ya se dijeron en el saludo: si el primer turno los volvía a
    anteponer, la llamada arrancaba con casi un minuto de avisos en dos tandas."""
    from app.agents.aviso_ia import AVISO_DATOS, AVISO_IA

    mock_llms(
        ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9),
        respuestas_ejecutor=[AIMessage(content="Atendemos de 8 a 14.")],
    )

    final = await voz.recibir_turno(db_session, telefono=TELEFONO, mensaje="¿Qué horario tienen?")

    assert AVISO_IA not in final["respuesta"]
    assert AVISO_DATOS not in final["respuesta"]
    assert final["respuesta"] == "Atendemos de 8 a 14."


async def test_recibir_turno_crea_el_caso_con_canal_voz(
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
                            "descripcion": "Hay un semáforo roto en la esquina",
                            "categoria": "infraestructura",
                        },
                        "id": "tc1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Registré su reclamo."),
        ],
    )

    final = await voz.recibir_turno(
        db_session, telefono=TELEFONO, mensaje="Hay un semáforo roto en la esquina"
    )

    caso = await db_session.get(Caso, uuid.UUID(final["caso_id"]))
    assert caso.tipo == TipoCaso.reclamo
    assert caso.canal_origen == Canal.voz

    interacciones = (
        (await db_session.execute(select(Interaccion).where(Interaccion.caso_id == caso.id)))
        .scalars()
        .all()
    )
    assert {i.canal for i in interacciones} == {Canal.voz}


async def test_un_ciudadano_que_ya_escribio_por_whatsapp_se_reconoce_por_voz(db_session):
    """Mismo teléfono, otro canal: continuidad cross-canal (ver
    `contexto.obtener_ciudadano_por_canal`, que ya resuelve Canal.voz por
    teléfono igual que WhatsApp)."""
    from app.channels import whatsapp

    por_whatsapp = await whatsapp.identificar_ciudadano(db_session, TELEFONO, "Marta Ruiz")
    por_voz = await voz.identificar_ciudadano(db_session, TELEFONO)

    assert por_whatsapp.id == por_voz.id
