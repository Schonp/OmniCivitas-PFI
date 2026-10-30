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


def test_sin_identificar_se_ofrecen_todas_las_gestiones():
    """La gestión pendiente está en el historial, no en el mensaje con el DNI."""
    from app.agents.ejecutor import construir_tools

    tools = construir_tools(
        None,
        {"ciudadano_id": str(uuid.uuid4()), "canal": "whatsapp", "intencion": "tramite", "identificado": False},
    )
    assert {t.name for t in tools} >= {"registrar_identidad", "crear_reclamo", "crear_reserva"}


async def test_el_nombre_y_el_dni_se_registran_sin_el_modelo(db_session, mocker):
    """El modelo volvía a pedir los datos que el ciudadano acababa de dar."""
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage as _AI

    from app.agents import ejecutor as mod

    persona = SimpleNamespace(id=uuid.uuid4(), nombre="Laura Prueba", documento="30111292")
    identificar = mocker.patch.object(mod.ciudadanos, "identificar_ciudadano", AsyncMock(return_value=persona))
    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(return_value=_AI(content="¿En qué lo puedo ayudar?"))
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    resultado = await mod.nodo_ejecutor(
        {
            "mensaje": "Laura Prueba, 30.111.292",
            "canal": "whatsapp",
            "identificador": "+5491100000088",
            "ciudadano_id": str(uuid.uuid4()),
            "identificado": False,
            "caso_id": None,
            "historial": [],
            "conocimiento": [],
            "intencion": "tramite",
            "entidades": {},
            "confianza": 0.9,
            "resultado_ejecucion": None,
            "requiere_escalado": False,
            "motivo_escalado": None,
            "respuesta": None,
        },
        db_session,
    )

    identificar.assert_awaited_once()
    assert identificar.await_args.kwargs == {"documento": "30111292", "nombre": "Laura Prueba"}
    assert resultado["identificado"] is True
    assert resultado["ciudadano_id"] == str(persona.id)
    assert resultado["respuesta"] == "Gracias, Laura. ¿En qué lo puedo ayudar?"


async def test_recien_identificado_no_se_le_vuelven_a_pedir_los_datos(db_session, mocker):
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage as _AI

    from app.agents import ejecutor as mod

    persona = SimpleNamespace(id=uuid.uuid4(), nombre="Laura Prueba", documento="30111292")
    mocker.patch.object(mod.ciudadanos, "identificar_ciudadano", AsyncMock(return_value=persona))
    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        return_value=_AI(content="Hola Laura. Para registrarlo necesito su nombre completo y su DNI.")
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    resultado = await mod.nodo_ejecutor(
        {
            "mensaje": "Soy Laura Prueba, DNI 30111292", "canal": "email", "identificador": "x@correo.test",
            "ciudadano_id": str(uuid.uuid4()), "identificado": False, "caso_id": None, "historial": [],
            "conocimiento": [], "intencion": "tramite", "entidades": {}, "confianza": 0.9,
            "resultado_ejecucion": None, "requiere_escalado": False, "motivo_escalado": None, "respuesta": None,
        },
        db_session,
    )

    assert resultado["respuesta"] == "Gracias, Laura. Ya registré sus datos. ¿En qué lo puedo ayudar?"


def test_no_se_le_muestra_el_identificador_interno_del_caso():
    from app.agents.ejecutor import _sin_identificadores_internos

    texto = (
        "Su reclamo está registrado.\n\nNúmero de caso: REC-1807DB61\n\n"
        "Número de caso: 1807db61-d26c-4459-8244-7c02fd22c1ea"
    )
    assert _sin_identificadores_internos(texto) == (
        "Su reclamo está registrado.\n\nNúmero de caso: REC-1807DB61"
    )


def test_las_pautas_del_organismo_van_antes_del_pedido_de_identificacion():
    """Una pauta como "en una emergencia, primero el número de emergencias" tiene
    que poder ir antes de pedir los datos. Con las pautas al final, el modelo
    obedecía siempre la identificación y las ignoraba."""
    from app.agents.ejecutor import (
        INSTRUCCION_IDENTIFICACION,
        SYSTEM_EJECUTOR,
        prompt_del_sistema,
    )
    from app.db.models import Canal

    sistema = prompt_del_sistema(
        Canal.whatsapp, pautas=["Trato: Tratar de usted."], identificado=False
    )

    assert "Trato: Tratar de usted." in sistema
    assert sistema.index(SYSTEM_EJECUTOR) < sistema.index("Trato: Tratar de usted.")
    assert sistema.index("Trato: Tratar de usted.") < sistema.index(INSTRUCCION_IDENTIFICACION)


def test_sin_pautas_el_prompt_no_cambia():
    """El dataset de entrenamiento y la medición del modelo arman el prompt sin
    pautas: tiene que ser el mismo texto de antes."""
    from app.agents.ejecutor import prompt_del_sistema
    from app.db.models import Canal

    assert "Pautas del organismo" not in prompt_del_sistema(Canal.whatsapp)


def test_dni_dicho_compara_solo_los_digitos():
    from app.agents.ejecutor import dni_dicho

    assert dni_dicho("30111295", ["Soy Laura, DNI 30.111.295"])
    assert dni_dicho("30.111.295", ["laura 30111295"])
    assert not dni_dicho("30111295", ["Me mordió un perro en la plaza"])


def test_dni_dicho_no_arma_un_dni_pegando_cifras_sueltas():
    """Una dirección y un número de casa juntos no son un DNI."""
    from app.agents.ejecutor import dni_dicho

    assert not dni_dicho("32001500", ["Rivadavia 3200, entre 1500 y 1600"])


async def test_no_se_registra_una_identidad_que_el_ciudadano_no_dio(db_session, mocker):
    """Pasó en una prueba con el modelo real: ante una mordedura, registró a un
    "Juan" con un DNI que nadie escribió. Si ese DNI fuera de otra persona, el
    contacto se le sumaría y vería sus casos."""
    from langchain_core.messages import AIMessage as _AI

    from app.agents import ejecutor as mod
    from app.db.models import Ciudadano

    ciudadano = Ciudadano(nombre="Sin nombre", documento="PROV-123", telefono="+5491100000077")
    db_session.add(ciudadano)
    await db_session.commit()

    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        side_effect=[
            _AI(
                content="",
                tool_calls=[
                    {
                        "name": "registrar_identidad",
                        "args": {"nombre_completo": "Juan Pérez", "documento": "30111295"},
                        "id": "t1",
                    }
                ],
            ),
            _AI(content="Para registrarlo necesito su nombre completo y su DNI."),
        ]
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    estado = {
        "mensaje": "Me mordió un perro suelto en la plaza",
        "canal": "whatsapp",
        "identificador": "+5491100000077",
        "ciudadano_id": str(ciudadano.id),
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
    }

    resultado = await mod.nodo_ejecutor(estado, db_session)

    await db_session.refresh(ciudadano)
    assert ciudadano.documento == "PROV-123"
    assert "registrar_identidad" not in (resultado.get("resultado_ejecucion") or {})


async def _laura_por_whatsapp_y_correo_provisorio(db_session, tipo_pendiente):
    """Laura ya existe por WhatsApp, con un reclamo; ahora escribe por correo
    sin identificarse y queda un registro provisorio con un caso abierto."""
    from app.db.models import Canal as _Canal
    from app.db.models import Caso, Ciudadano, TipoCaso

    laura = Ciudadano(nombre="Laura Prueba", documento="30111295", telefono="+5491100000095")
    provisorio = Ciudadano(nombre="Laura", documento="PROV-F5", email="laura@correo.test")
    db_session.add_all([laura, provisorio])
    await db_session.flush()
    reclamo = Caso(
        ciudadano_id=laura.id,
        tipo=TipoCaso.reclamo,
        canal_origen=_Canal.whatsapp,
        canal_actual=_Canal.whatsapp,
        asunto="Pozo en la calzada en Av. Rivadavia 3200",
    )
    pendiente = Caso(
        ciudadano_id=provisorio.id,
        tipo=tipo_pendiente,
        canal_origen=_Canal.email,
        canal_actual=_Canal.email,
    )
    db_session.add_all([reclamo, pendiente])
    await db_session.commit()
    return laura, provisorio, reclamo, pendiente


def _estado_f5(provisorio, pendiente, pregunta):
    return {
        "mensaje": "Soy Laura Prueba, DNI 30111295",
        "canal": "email",
        "identificador": "laura@correo.test",
        "ciudadano_id": str(provisorio.id),
        "identificado": False,
        "caso_id": str(pendiente.id),
        "historial": [{"actor": "ciudadano", "contenido": pregunta, "canal": "email"}],
        "conocimiento": [],
        "intencion": "tramite",
        "entidades": {},
        "confianza": 0.9,
        "resultado_ejecucion": None,
        "requiere_escalado": False,
        "motivo_escalado": None,
        "respuesta": None,
    }


async def test_quien_se_identifica_por_otro_canal_recibe_el_estado_de_su_caso(
    db_session, mocker
):
    """Caso funcional F5. El modelo tomaba la pregunta del historial como un
    reclamo nuevo, inventaba una dirección y el caso terminaba derivado."""
    from app.agents import ejecutor as mod
    from app.db.models import TipoCaso

    laura, provisorio, reclamo, pendiente = await _laura_por_whatsapp_y_correo_provisorio(
        db_session, TipoCaso.consulta
    )
    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(side_effect=AssertionError("no hace falta el modelo"))
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    resultado = await mod.nodo_ejecutor(
        _estado_f5(provisorio, pendiente, "¿Cómo va el reclamo del pozo?"), db_session
    )

    assert resultado["ciudadano_id"] == str(laura.id)
    assert resultado["respuesta"].startswith("Gracias, Laura. Ya sumé este correo a su registro.")
    assert reclamo.referencia in resultado["respuesta"]
    assert "pozo" in resultado["respuesta"]
    assert resultado.get("requiere_escalado") is not True


async def test_si_lo_pendiente_era_un_reclamo_lo_sigue_gestionando_el_modelo(
    db_session, mocker
):
    """Si por el canal nuevo contó un problema, eso es un reclamo para crear,
    no una consulta de estado."""
    from langchain_core.messages import AIMessage as _AI

    from app.agents import ejecutor as mod
    from app.db.models import TipoCaso

    _, provisorio, _, pendiente = await _laura_por_whatsapp_y_correo_provisorio(
        db_session, TipoCaso.reclamo
    )
    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(return_value=_AI(content="¿En qué calle está?"))
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    await mod.nodo_ejecutor(
        _estado_f5(provisorio, pendiente, "Hay un árbol caído en mi cuadra"), db_session
    )

    assert modelo.bind_tools.return_value.ainvoke.await_count == 1


async def test_f5_aunque_el_intake_haya_dicho_reclamo(db_session, mocker):
    """Pasó con la v3: "¿cómo va el reclamo del pozo?" salió reclamo por la
    palabra, y con el DNI se derivaba en vez de dar el estado. La pregunta por
    el estado manda sobre el tipo, y el caso pasa a ser una consulta."""
    from app.agents import ejecutor as mod
    from app.db.models import TipoCaso

    laura, provisorio, reclamo, pendiente = await _laura_por_whatsapp_y_correo_provisorio(
        db_session, TipoCaso.reclamo
    )
    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(side_effect=AssertionError("no hace falta el modelo"))
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    resultado = await mod.nodo_ejecutor(
        _estado_f5(provisorio, pendiente, "Hola, ¿cómo va el reclamo del pozo?"), db_session
    )

    assert resultado["respuesta"].startswith("Gracias, Laura. Ya sumé este correo a su registro.")
    assert reclamo.referencia in resultado["respuesta"]
    await db_session.refresh(pendiente)
    assert pendiente.tipo == TipoCaso.consulta


async def test_un_contacto_nuevo_que_pregunta_por_su_caso_da_sus_datos(db_session, mocker):
    """Contestarle "no encontré casos a su nombre" a quien inició el reclamo por
    otro canal es falso: se le piden los datos para buscarlo."""
    from langchain_core.messages import AIMessage as _AI

    from app.agents import ejecutor as mod
    from app.agents.confirmacion import pedido_de_identificacion_para_consulta
    from app.db.models import Canal as _Canal
    from app.db.models import Ciudadano

    provisorio = Ciudadano(nombre="Laura", documento="PROV-NUEVO", email="nueva@correo.test")
    db_session.add(provisorio)
    await db_session.commit()
    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        return_value=_AI(
            content="",
            tool_calls=[{"name": "consultar_estado_caso", "args": {"referencia": "reclamo del pozo"}, "id": "c1"}],
        )
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)
    estado = {
        "mensaje": "¿Cómo va el reclamo del pozo?",
        "canal": "email",
        "identificador": "nueva@correo.test",
        "ciudadano_id": str(provisorio.id),
        "identificado": False,
        "caso_id": None,
        "historial": [],
        "intencion": "reclamo",
    }

    resultado = await mod.nodo_ejecutor(estado, db_session)

    assert resultado["respuesta"] == pedido_de_identificacion_para_consulta(_Canal.email)


def test_si_el_modelo_inventa_datos_el_reclamo_va_con_las_palabras_del_ciudadano():
    from app.agents.ejecutor import datos_inventados, descripcion_del_ciudadano

    dichos = [
        "Laura Prueba, DNI 30775211",
        "Hola, hay un pozo enorme en Av. Rivadavia 3200 y ayer se cayó una moto",
    ]
    del_modelo = "Pozo en Av. Rivadavia 3200 entre Avellaneda y Belgrano"
    assert datos_inventados(del_modelo, dichos)

    assert descripcion_del_ciudadano(del_modelo, dichos) == (
        "Hay un pozo enorme en Av. Rivadavia 3200 y ayer se cayó una moto"
    )


def test_sin_un_mensaje_que_cuente_lo_mismo_no_hay_descripcion_propia():
    from app.agents.ejecutor import descripcion_del_ciudadano

    dichos = ["Laura Prueba, DNI 30775211", "Quiero hacer un reclamo"]
    assert descripcion_del_ciudadano("Pozo en Lavalle y Córdoba 1200", dichos) is None


async def test_dos_reclamos_en_la_misma_respuesta_se_registran_una_vez(db_session, ciudadano, mocker):
    """Pasó con la v3: dos `crear_reclamo` del mismo pozo y la confirmación
    salía dos veces."""
    from langchain_core.messages import AIMessage as _AI

    from app.agents import ejecutor as mod

    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        return_value=_AI(
            content="",
            tool_calls=[
                {
                    "name": "crear_reclamo",
                    "args": {"descripcion": "Pozo en Thames 1200", "categoria": "infraestructura"},
                    "id": "c1",
                },
                {
                    "name": "crear_reclamo",
                    "args": {"descripcion": "Moto caída en pozo en Thames 1200", "categoria": "infraestructura"},
                    "id": "c2",
                },
            ],
        )
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)
    estado = {
        "mensaje": "Hay un pozo en Thames 1200 y se cayó una moto",
        "canal": "email",
        "identificador": ciudadano.email,
        "ciudadano_id": str(ciudadano.id),
        "identificado": True,
        "caso_id": None,
        "historial": [],
        "intencion": "reclamo",
    }

    resultado = await mod.nodo_ejecutor(estado, db_session)

    assert resultado["respuesta"].count("Número de caso") == 1


async def test_a_quien_ya_esta_identificado_no_se_le_vuelven_a_pedir_los_datos(
    db_session, ciudadano, mocker
):
    """Pasó con la v3: identificada por correo, preguntó para cuándo arreglaban
    el pozo y el modelo le volvió a pedir nombre y DNI. Se corrige una vez; si
    insiste, va un texto fijo."""
    from langchain_core.messages import AIMessage as _AI

    from app.agents import ejecutor as mod

    pide_datos = _AI(content="Lo puedo consultar, pero necesito su nombre completo y su DNI.")
    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        side_effect=[pide_datos, _AI(content="El bacheo se hace dentro de los 10 días hábiles.")]
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)
    estado = {
        "mensaje": "¿Y para cuándo calculan que lo arreglan?",
        "canal": "email",
        "identificador": ciudadano.email,
        "ciudadano_id": str(ciudadano.id),
        "identificado": True,
        "caso_id": None,
        "historial": [],
        "intencion": "consulta",
    }

    resultado = await mod.nodo_ejecutor(estado, db_session)
    assert resultado["respuesta"] == "El bacheo se hace dentro de los 10 días hábiles."

    modelo.bind_tools.return_value.ainvoke = AsyncMock(side_effect=[pide_datos, pide_datos])
    resultado = await mod.nodo_ejecutor(estado, db_session)
    assert resultado["respuesta"] == mod.NO_TENGO_ESE_DATO


def test_se_quita_un_numero_de_caso_que_no_es_del_ciudadano():
    """Pasó con el modelo real: "Número de caso: REC-20194FB3" con el caso real
    REC-20194FB2."""
    from app.agents.ejecutor import sin_referencias_ajenas

    texto = "Lave la herida con agua y jabón.\n\nNúmero de caso: REC-20194FB3"

    assert sin_referencias_ajenas(texto, {"REC-20194FB2"}) == "Lave la herida con agua y jabón."
    assert sin_referencias_ajenas(texto, {"REC-20194FB3"}) == texto


async def test_el_ejecutor_no_deja_pasar_un_numero_de_caso_inventado(db_session, mocker, ciudadano):
    from langchain_core.messages import AIMessage as _AI

    from app.agents import ejecutor as mod

    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        return_value=_AI(content="Lave la herida con agua y jabón.\n\nNúmero de caso: REC-ABCDEF12")
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    estado = {
        "mensaje": "Me mordió un perro, ¿qué hago?",
        "canal": "whatsapp",
        "identificador": "+5491122334455",
        "ciudadano_id": str(ciudadano.id),
        "identificado": True,
        "caso_id": None,
        "historial": [],
        "conocimiento": [],
        "intencion": "consulta",
        "entidades": {},
        "confianza": 0.9,
        "resultado_ejecucion": None,
        "requiere_escalado": False,
        "motivo_escalado": None,
        "respuesta": None,
    }

    resultado = await mod.nodo_ejecutor(estado, db_session)

    assert resultado["respuesta"] == "Lave la herida con agua y jabón."


async def test_el_aviso_que_acompana_la_llamada_queda_antes_de_la_confirmacion(db_session, ciudadano, mocker):
    """Una pauta de emergencias: el número va antes de la confirmación del reclamo."""
    from langchain_core.messages import AIMessage as _AI

    from app.agents import ejecutor as mod

    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        return_value=_AI(
            content="Por favor, que nadie se acerque al cable. Si hay riesgo inmediato, llame al 911.",
            tool_calls=[{"name": "crear_reclamo", "args": {
                "descripcion": "Cable caído en Av. Corrientes 1500", "categoria": "infraestructura"}, "id": "t1"}],
        )
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)
    estado = {
        "mensaje": "Hay un cable caído en Av. Corrientes 1500 y saltan chispas", "canal": "whatsapp",
        "identificador": ciudadano.telefono, "ciudadano_id": str(ciudadano.id), "identificado": True,
        "caso_id": None, "historial": [], "conocimiento": [], "intencion": "reclamo", "entidades": {},
        "confianza": 0.9, "resultado_ejecucion": None, "requiere_escalado": False,
        "motivo_escalado": None, "respuesta": None,
    }

    resultado = await mod.nodo_ejecutor(estado, db_session)

    assert resultado["respuesta"].startswith("Por favor, que nadie se acerque al cable.")
    assert "Registré su reclamo" in resultado["respuesta"]
