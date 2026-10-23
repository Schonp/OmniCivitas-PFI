import uuid
from unittest.mock import AsyncMock, MagicMock

async def test_el_ejecutor_recibe_el_historial_como_turnos_previos(db_session, mocker):
    """Sin esto el agente vuelve a preguntar algo que el ciudadano ya dijo en un
    mensaje anterior, que es exactamente lo que el proyecto busca evitar."""
    from langchain_core.messages import AIMessage as _AI
    from langchain_core.messages import HumanMessage as _H
    from langchain_core.messages import SystemMessage as _S

    from app.agents import ejecutor as mod

    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        return_value=_AI(content="Le reservo el turno de licencia.")
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    estado = {
        "mensaje": "El martes a las 10",
        "canal": "email",
        "identificador": "vecina@correo.test",
        "ciudadano_id": str(uuid.uuid4()),
        "identificado": True,
        "caso_id": None,
        "historial": [
            {"actor": "ciudadano", "contenido": "Quiero renovar la licencia", "canal": "email"},
            {"actor": "agente_ia", "contenido": "¿Qué día le queda cómodo?", "canal": "email"},
        ],
        "conocimiento": [],
        "intencion": "reserva",
        "entidades": {},
        "confianza": 0.9,
        "resultado_ejecucion": None,
        "requiere_escalado": False,
        "motivo_escalado": None,
        "respuesta": None,
    }

    await mod.nodo_ejecutor(estado, db_session)

    enviados = modelo.bind_tools.return_value.ainvoke.await_args.args[0]
    assert isinstance(enviados[0], _S)
    # El turno previo del ciudadano viaja como tal, y el del agente como respuesta.
    assert [type(m) for m in enviados[1:]] == [_H, _AI, _H]
    assert enviados[1].content == "Quiero renovar la licencia"
    assert enviados[-1].content == "El martes a las 10"


async def test_derivar_a_operador_esta_siempre_disponible(db_session):
    """El ciudadano tiene que poder llegar a una persona sea cual sea la intención:
    fue lo segundo más pedido en la encuesta."""
    from app.agents.ejecutor import construir_tools

    for intencion in ("reclamo", "reserva", "consulta", "tramite", None):
        estado = {
            "ciudadano_id": str(uuid.uuid4()),
            "canal": "email",
            "intencion": intencion,
            "identificado": True,
        }
        nombres = [t.name for t in construir_tools(db_session, estado)]
        assert "derivar_a_operador" in nombres, intencion


async def test_si_el_agente_deriva_el_caso_escala(db_session, mocker):
    from langchain_core.messages import AIMessage as _AI

    from app.agents import ejecutor as mod

    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        side_effect=[
            _AI(
                content="",
                tool_calls=[
                    {
                        "name": "derivar_a_operador",
                        "args": {"motivo": "Pide datos que el agente no tiene"},
                        "id": "tc1",
                        "type": "tool_call",
                    }
                ],
            ),
            _AI(content="Lo derivo a un operador."),
        ]
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    estado = {
        "mensaje": "¿Cuántos habitantes tiene el municipio?",
        "canal": "email",
        "identificador": "vecina@correo.test",
        "ciudadano_id": str(uuid.uuid4()),
        "identificado": True,
        "caso_id": None,
        "historial": [],
        "conocimiento": [],
        "intencion": "consulta",
        "entidades": {},
        "confianza": 0.95,
        "resultado_ejecucion": None,
        "requiere_escalado": False,
        "motivo_escalado": None,
        "respuesta": None,
    }

    resultado = await mod.nodo_ejecutor(estado, db_session)

    assert resultado["requiere_escalado"] is True
    assert resultado["motivo_escalado"] == "sin_herramienta"
    # No se le contesta "no puedo" y listo: el escalado arma la respuesta.
    assert "respuesta" not in resultado


def test_se_quita_el_markdown_de_la_respuesta():
    """WhatsApp usa un solo asterisco para la negrita y el correo va en texto
    plano: un `**` del modelo llega literal a la pantalla del ciudadano."""
    from app.agents.ejecutor import _sin_markdown

    assert _sin_markdown("su reclamo **REC-8A72DCBD**") == "su reclamo REC-8A72DCBD"
    assert _sin_markdown("__urgente__") == "urgente"
    assert _sin_markdown("## Resumen\ntexto") == "Resumen\ntexto"
    # Un asterisco suelto no es marcado y no se toca.
    assert _sin_markdown("horario 8*") == "horario 8*"
    assert _sin_markdown("sin marcas") == "sin marcas"


async def test_el_conocimiento_llega_al_prompt_con_la_consigna_de_usarlo(
    db_session, mocker
):
    """El ejecutor derivaba consultas que ya podía contestar.

    El prompt definía "resolver" como "usar una herramienta", así que ante una
    pregunta de requisitos el modelo no encontraba tool y llamaba a
    derivar_a_operador con el documento de la base de conocimiento delante. La
    decisión la toma el modelo, pero lo que sí se puede fijar acá es que la
    información y la instrucción de usarla efectivamente le lleguen.
    """
    from langchain_core.messages import AIMessage as _AI

    from app.agents import ejecutor as mod

    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        return_value=_AI(content="Necesita la licencia anterior y el DNI vigente.")
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    estado = {
        "mensaje": "Qué necesito para renovar la licencia",
        "canal": "email",
        "identificador": "vecina@correo.test",
        "ciudadano_id": str(uuid.uuid4()),
        "identificado": True,
        "caso_id": None,
        "historial": [],
        "conocimiento": [
            "Requisitos para renovar la licencia: licencia anterior y DNI vigente."
        ],
        "intencion": "consulta",
        "entidades": {},
        "confianza": 0.9,
        "resultado_ejecucion": None,
        "requiere_escalado": False,
        "motivo_escalado": None,
        "respuesta": None,
    }

    resultado = await mod.nodo_ejecutor(estado, db_session)

    sistema = modelo.bind_tools.return_value.ainvoke.await_args.args[0][0].content
    assert "licencia anterior y DNI vigente" in sistema
    # Sin esta consigna el modelo trata la consulta como algo que no puede resolver.
    assert "no llames a ninguna herramienta" in sistema

    # Contestar sin usar tools no es un fallo: no escala.
    assert resultado.get("requiere_escalado") is not True
    assert "DNI vigente" in resultado["respuesta"]


def test_el_prompt_no_manda_a_derivar_lo_que_se_puede_contestar():
    """La regla vieja ("si no podés con las herramientas, derivá") convertía a la
    derivación en el destino por defecto de toda consulta informativa."""
    from app.agents.ejecutor import SYSTEM_EJECUTOR

    assert "Nunca derives una consulta que ya podés contestar" in SYSTEM_EJECUTOR
    assert "informar" in SYSTEM_EJECUTOR


async def test_sin_dni_no_se_crea_el_reclamo_y_se_piden_los_datos(db_session, mocker):
    """El modelo a veces crea el reclamo aunque el prompt le pida identificar
    primero: el ejecutor no lo deja correr y le pide nombre y DNI."""
    from langchain_core.messages import AIMessage as _AI

    from app.agents import ejecutor as mod

    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        return_value=_AI(
            content="",
            tool_calls=[
                {
                    "name": "crear_reclamo",
                    "args": {"descripcion": "Pozo en Av. Rivadavia 3200", "categoria": "infraestructura"},
                    "id": "tc1",
                    "type": "tool_call",
                }
            ],
        )
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)
    crear = mocker.patch.object(mod.reclamos, "crear_reclamo")

    resultado = await mod.nodo_ejecutor(
        {
            "mensaje": "Hay un pozo en Av. Rivadavia 3200",
            "canal": "whatsapp",
            "identificador": "+5491100000088",
            "ciudadano_id": str(uuid.uuid4()),
            "identificado": False,
            "caso_id": None,
            "historial": [],
            "conocimiento": [],
            "intencion": "reclamo",
            "entidades": {},
            "confianza": 0.9,
            "resultado_ejecucion": None,
            "requiere_escalado": False,
            "motivo_escalado": None,
            "respuesta": None,
        },
        db_session,
    )

    crear.assert_not_called()
    assert resultado["respuesta"].startswith("Tomé nota de su reclamo.")
    assert "DNI" in resultado["respuesta"]
