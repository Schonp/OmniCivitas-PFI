import uuid
from email.message import EmailMessage

from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.channels import email as canal_email
from app.channels import whatsapp
from app.db.crud.ciudadanos import crear_ciudadano, documento_provisorio
from app.db.models import (
    ActorInteraccion,
    Canal,
    Caso,
    Ciudadano,
    EstadoCaso,
    Interaccion,
    TipoCaso,
)
from app.schemas.agente import ClasificacionIntent
from app.schemas.ciudadano import CiudadanoCreate

DIRECCION = "vecina@correo.test"


def _correo(cuerpo: str, *, asunto: str = "Consulta", html: bool = False) -> EmailMessage:
    mensaje = EmailMessage()
    mensaje["From"] = f"Marta Ruiz <{DIRECCION}>"
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo)
    if html:
        mensaje.add_alternative("<p>ignorame</p>", subtype="html")
    return mensaje


def test_texto_plano_ignora_la_parte_html():
    assert "ignorame" not in canal_email._texto_plano(_correo("Hola", html=True))
    assert "Hola" in canal_email._texto_plano(_correo("Hola", html=True))


def test_quitar_citas_corta_en_la_respuesta_anterior():
    cuerpo = (
        "Quería saber el estado de mi reclamo.\n"
        "\n"
        "El 12 de agosto, OmniCivitas escribió:\n"
        "> Su reclamo fue registrado con el número REC-1042\n"
    )

    assert canal_email._quitar_citas(cuerpo) == "Quería saber el estado de mi reclamo."


def test_quitar_citas_corta_en_la_linea_citada_directa():
    cuerpo = "Gracias.\n> texto anterior que no hay que reenviar"

    assert canal_email._quitar_citas(cuerpo) == "Gracias."


def test_documento_provisorio_entra_en_la_columna():
    documento = documento_provisorio(DIRECCION)

    assert documento.startswith("SIN-DNI-")
    assert len(documento) <= 20


async def test_identificar_ciudadano_da_de_alta_en_primer_contacto(db_session):
    ciudadano = await canal_email.identificar_ciudadano(db_session, DIRECCION, "Marta Ruiz")

    assert ciudadano.email == DIRECCION
    assert ciudadano.nombre == "Marta Ruiz"
    assert ciudadano.documento.startswith("SIN-DNI-")


async def test_identificar_ciudadano_reutiliza_el_email_existente(db_session):
    existente = await crear_ciudadano(
        db_session,
        CiudadanoCreate(documento="28456789", nombre="Marta Ruiz", email=DIRECCION),
    )

    identificado = await canal_email.identificar_ciudadano(db_session, DIRECCION)

    assert identificado.id == existente.id
    assert identificado.documento == "28456789"


async def test_recibir_mensaje_crea_el_caso_con_canal_email(
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
                        "args": {"descripcion": "Poste quemado", "categoria": "servicio"},
                        "id": "tc1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Registré su reclamo."),
        ],
    )

    final = await canal_email.recibir_mensaje(
        db_session, direccion=DIRECCION, mensaje="El poste no anda", nombre="Marta Ruiz"
    )

    caso = await db_session.get(Caso, uuid.UUID(final["caso_id"]))
    assert caso.tipo == TipoCaso.reclamo
    assert caso.canal_origen == Canal.email
    interacciones = (
        (await db_session.execute(select(Interaccion).where(Interaccion.caso_id == caso.id)))
        .scalars()
        .all()
    )
    assert {i.canal for i in interacciones} == {Canal.email}


async def test_el_caso_continua_al_cambiar_de_whatsapp_a_email(
    db_session, mock_llms, checkpointer_en_memoria
):
    """El aporte central de la tesis: el mismo ciudadano escribe por WhatsApp y
    después por correo, y sigue siendo el mismo caso, con el cambio auditado."""
    ciudadano = await crear_ciudadano(
        db_session,
        CiudadanoCreate(
            documento="28456789",
            nombre="Marta Ruiz",
            email=DIRECCION,
            telefono="+5491133334444",
        ),
    )

    mock_llms(
        [
            ClasificacionIntent(intencion="reclamo", entidades={}, confianza=0.9),
            ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9),
        ],
        respuestas_ejecutor=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "crear_reclamo",
                        "args": {"descripcion": "Poste quemado", "categoria": "servicio"},
                        "id": "tc1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Registré su reclamo."),
            AIMessage(content="Su reclamo está en progreso. No necesita volver a cargarlo."),
        ],
    )

    primero = await whatsapp.recibir_mensaje(
        db_session, telefono=ciudadano.telefono, mensaje="El poste no anda"
    )
    segundo = await canal_email.recibir_mensaje(
        db_session, direccion=DIRECCION, mensaje="¿Cómo viene el reclamo?"
    )

    assert primero["caso_id"] == segundo["caso_id"]

    caso = await db_session.get(Caso, uuid.UUID(segundo["caso_id"]))
    await db_session.refresh(caso)
    assert caso.canal_origen == Canal.whatsapp
    assert caso.canal_actual == Canal.email

    interacciones = (
        (await db_session.execute(select(Interaccion).where(Interaccion.caso_id == caso.id)))
        .scalars()
        .all()
    )
    assert {i.canal for i in interacciones} == {Canal.whatsapp, Canal.email}
    assert ActorInteraccion.agente_ia in {i.actor for i in interacciones}


async def test_procesar_buzon_responde_cada_correo(db_session, mocker):
    # El destino ahora sale del registro del ciudadano, no del sobre del correo.
    db_session.add(Ciudadano(documento="55444555", nombre="Marta", email=DIRECCION))
    await db_session.commit()

    entrante = canal_email.CorreoEntrante(
        remitente=DIRECCION, nombre="Marta", asunto="Consulta", cuerpo="¿Horarios?"
    )
    mocker.patch.object(canal_email, "consultar_buzon", return_value=[entrante])
    mocker.patch.object(
        canal_email,
        "recibir_mensaje",
        return_value={"respuesta": "Atendemos de 8 a 14."},
    )
    enviar = mocker.patch.object(canal_email, "enviar_mensaje")

    procesados = await canal_email.procesar_buzon(db_session)

    assert procesados == 1
    enviar.assert_awaited_once_with(DIRECCION, "Atendemos de 8 a 14.", "Re: Consulta")


async def test_procesar_buzon_sigue_con_el_resto_si_uno_falla(db_session, mocker):
    db_session.add(Ciudadano(documento="55666777", nombre="Otro", email="otro@correo.test"))
    await db_session.commit()

    correos = [
        canal_email.CorreoEntrante(DIRECCION, "Marta", "Uno", "primero"),
        canal_email.CorreoEntrante("otro@correo.test", "Otro", "Dos", "segundo"),
    ]
    mocker.patch.object(canal_email, "consultar_buzon", return_value=correos)
    mocker.patch.object(
        canal_email,
        "recibir_mensaje",
        side_effect=[RuntimeError("falló el grafo"), {"respuesta": "ok"}],
    )
    enviar = mocker.patch.object(canal_email, "enviar_mensaje")

    procesados = await canal_email.procesar_buzon(db_session)

    assert procesados == 2
    enviar.assert_awaited_once_with("otro@correo.test", "ok", "Re: Dos")


def test_leer_no_leidos_ignora_correos_de_la_propia_casilla(mocker):
    """Sin este corte, la casilla del organismo y un autorespondedor del
    ciudadano se contestarían en bucle."""
    mocker.patch.object(canal_email.settings, "imap_host", "imap.test")
    mocker.patch.object(canal_email.settings, "imap_user", "organismo@test.com")

    propio = EmailMessage()
    propio["From"] = "Organismo <organismo@test.com>"
    propio["Subject"] = "Re: consulta"
    propio.set_content("respuesta automática anterior")

    buzon = mocker.MagicMock()
    buzon.__enter__.return_value = buzon
    buzon.search.return_value = ("OK", [b"1"])
    buzon.fetch.return_value = ("OK", [(b"1", propio.as_bytes())])
    mocker.patch.object(canal_email.imaplib, "IMAP4_SSL", return_value=buzon)

    assert canal_email._leer_no_leidos() == []


async def test_una_consulta_sin_tool_igual_abre_caso_y_deja_registro(
    db_session, mock_llms, checkpointer_en_memoria
):
    """Antes, si el ejecutor respondía sin llamar ninguna tool, no se creaba caso
    y se perdía todo: mensaje del ciudadano, respuesta y auditoría."""
    from sqlalchemy import select as _select

    from app.db.models import Auditoria

    mock_llms(
        ClasificacionIntent(intencion="reserva", entidades={}, confianza=0.9),
        respuestas_ejecutor=[
            AIMessage(content="¿Qué día y horario le queda cómodo para el turno?")
        ],
    )

    final = await canal_email.recibir_mensaje(
        db_session, direccion=DIRECCION, mensaje="Quiero un turno para la licencia"
    )

    assert final["caso_id"] is not None
    caso = await db_session.get(Caso, uuid.UUID(final["caso_id"]))
    assert caso.tipo == TipoCaso.reserva
    assert caso.canal_origen == Canal.email

    interacciones = (
        (await db_session.execute(_select(Interaccion).where(Interaccion.caso_id == caso.id)))
        .scalars()
        .all()
    )
    assert {i.actor for i in interacciones} == {
        ActorInteraccion.ciudadano,
        ActorInteraccion.agente_ia,
    }

    acciones = {
        a.accion
        for a in (
            await db_session.execute(_select(Auditoria).where(Auditoria.caso_id == caso.id))
        )
        .scalars()
        .all()
    }
    assert "apertura_caso" in acciones
    assert "respuesta_ia" in acciones


async def test_al_ciudadano_no_identificado_se_le_pide_el_dni_primero(
    db_session, mock_llms, checkpointer_en_memoria, mocker
):
    """El primer contacto de un remitente desconocido no gestiona nada: pide
    nombre y documento, porque el organismo los necesita para actuar a su nombre."""
    from app.agents import ejecutor

    espia = mocker.spy(ejecutor, "construir_tools")
    mock_llms(
        ClasificacionIntent(intencion="reserva", entidades={}, confianza=0.9),
        respuestas_ejecutor=[
            AIMessage(content="Para gestionar su turno necesito su nombre completo y su DNI.")
        ],
    )

    await canal_email.recibir_mensaje(
        db_session, direccion=DIRECCION, mensaje="Quiero un turno para la licencia"
    )

    estado = espia.call_args.args[1]
    assert estado["identificado"] is False
    assert "registrar_identidad" in [t.name for t in espia.spy_return]


async def test_el_ciudadano_del_padron_no_recibe_el_pedido_de_identificacion(
    db_session, mock_llms, checkpointer_en_memoria, mocker
):
    from app.agents import ejecutor

    await crear_ciudadano(
        db_session,
        CiudadanoCreate(documento="28456789", nombre="Marta Ruiz", email=DIRECCION),
    )
    espia = mocker.spy(ejecutor, "construir_tools")
    mock_llms(
        ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9),
        respuestas_ejecutor=[AIMessage(content="Atendemos de 8 a 14.")],
    )

    await canal_email.recibir_mensaje(
        db_session, direccion=DIRECCION, mensaje="¿Cuál es el horario?"
    )

    assert espia.call_args.args[1]["identificado"] is True


async def test_el_ciudadano_que_contesta_tras_la_derivacion_sigue_en_el_mismo_caso(
    db_session, mock_llms, checkpointer_en_memoria
):
    """Un caso derivado sigue vivo hasta que alguien lo cierre.

    `escalado` quedaba fuera de la búsqueda del caso activo, así que el correo
    siguiente del ciudadano no encontraba su caso y abría uno nuevo: la
    conversación quedaba partida en dos y el operador respondía sobre un hilo
    que el ciudadano ya no estaba usando.
    """
    ciudadano = await crear_ciudadano(
        db_session,
        CiudadanoCreate(documento="28456789", nombre="Marta Ruiz", email=DIRECCION),
    )

    # "tramite" escala siempre: todavía no tiene tool.
    mock_llms(
        [
            ClasificacionIntent(intencion="tramite", entidades={}, confianza=0.9),
            ClasificacionIntent(intencion="tramite", entidades={}, confianza=0.9),
        ]
    )

    derivado = await canal_email.recibir_mensaje(
        db_session, direccion=DIRECCION, mensaje="Necesito renovar la licencia"
    )
    caso = await db_session.get(Caso, uuid.UUID(derivado["caso_id"]))
    await db_session.refresh(caso)
    assert caso.estado == EstadoCaso.escalado

    seguimiento = await canal_email.recibir_mensaje(
        db_session, direccion=DIRECCION, mensaje="Le paso el número de trámite: 4821"
    )

    assert seguimiento["caso_id"] == derivado["caso_id"]

    casos = (
        (await db_session.execute(select(Caso).where(Caso.ciudadano_id == ciudadano.id)))
        .scalars()
        .all()
    )
    assert len(casos) == 1

    contenidos = [
        i.contenido
        for i in (
            await db_session.execute(
                select(Interaccion).where(Interaccion.caso_id == caso.id)
            )
        )
        .scalars()
        .all()
    ]
    assert "Le paso el número de trámite: 4821" in contenidos
