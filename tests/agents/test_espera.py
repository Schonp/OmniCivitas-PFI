"""Un caso en manos de una persona no lo retoma el agente.

Después de derivar, el ciudadano igual escribe. Ese mensaje tiene que quedar en
el caso derivado sin que el agente lo conteste como si nada hubiera pasado: no
puede resolver lo que ya se decidió que resuelve un humano, y contestando
pisaría el resumen con el que el operador retoma y sacaría el caso de la cola.
"""

import uuid

import pytest
from datetime import datetime, timedelta, timezone

from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.agents.espera import mensaje_espera
from app.core.config import settings
from app.agents.graph import decidir_ruta, procesar_mensaje
from app.agents.saludo import MENU
from app.db.models import (
    ActorInteraccion,
    Auditoria,
    Canal,
    Caso,
    EstadoCaso,
    Interaccion,
    TipoCaso,
)
from app.schemas.agente import ClasificacionIntent


@pytest.fixture
def ventana_de_silencio(mocker):
    """Fija la ventana en 30 minutos.

    Sin esto el valor del `.env` de cada máquina decide si estos tests pasan:
    bajarlo a 2 para una demo alcanzaba para romperlos.
    """
    mocker.patch.object(settings, "agente_minutos_silencio_derivado", 30)
    return 30


def _estado(**overrides) -> dict:
    base = {
        "mensaje": "le paso el dato que me pidieron",
        "canal": "email",
        "identificador": "vecina@correo.test",
        "ciudadano_id": "algun-uuid",
        "caso_id": str(uuid.uuid4()),
        "en_manos_humanas": True,
        "intencion": "consulta",
        "confianza": 0.9,
        "requiere_escalado": False,
    }
    return {**base, **overrides}


def test_routing_manda_a_espera_si_el_caso_ya_lo_tiene_una_persona():
    assert decidir_ruta(_estado()) == "espera"


def test_espera_gana_sobre_un_pedido_de_humano():
    """Volver a pasar por escalado regeneraría el resumen_ia con el que el
    operador está trabajando, con el texto de este mensaje suelto."""
    assert decidir_ruta(_estado(requiere_escalado=True)) == "espera"


def test_espera_gana_sobre_la_confianza_baja():
    assert decidir_ruta(_estado(confianza=0.1)) == "espera"


def test_un_caso_en_manos_del_agente_sigue_su_curso():
    assert decidir_ruta(_estado(en_manos_humanas=False)) == "ejecutor"


def test_la_cortesia_sobre_un_caso_derivado_no_se_va_por_saludo():
    """El bug que se vio en producción: el ciudadano contestó "OK, gracias por
    avisar" al operador y el intake lo clasificó como saludo. Con este chequeo
    después del de saludo, `nodo_saludo` descartaba el caso_id y el mensaje no
    se persistía en ningún lado: desaparecía del caso y el ciudadano recibía el
    saludo genérico ofreciéndole tomar un reclamo."""
    assert decidir_ruta(_estado(intencion="saludo")) == "espera"


def test_un_saludo_sin_caso_en_manos_humanas_se_contesta_como_saludo():
    assert decidir_ruta(_estado(intencion="saludo", en_manos_humanas=False)) == "saludo"


async def test_el_caso_derivado_no_lo_retoma_el_agente(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    caso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.tramite,
        estado=EstadoCaso.escalado,
        canal_origen=Canal.email,
        canal_actual=Canal.email,
        resumen_ia="El vecino pide renovar la licencia de conducir.",
    )
    db_session.add(caso)
    await db_session.commit()

    mock_llms(
        ClasificacionIntent(intencion="tramite", entidades={}, confianza=0.9),
        respuestas_ejecutor=[AIMessage(content="no debería usarse")],
    )

    final = await procesar_mensaje(
        db_session,
        mensaje="Mi número de trámite es 4821",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=checkpointer_en_memoria,
    )

    assert final["caso_id"] == str(caso.id)
    assert final["respuesta"].endswith(mensaje_espera(caso.referencia))

    await db_session.refresh(caso)
    assert caso.estado == EstadoCaso.escalado
    assert caso.resumen_ia == "El vecino pide renovar la licencia de conducir.", (
        "el resumen del operador no se pisa con el mensaje suelto"
    )

    acciones = (
        (await db_session.execute(select(Auditoria.accion).where(Auditoria.caso_id == caso.id)))
        .scalars()
        .all()
    )
    assert "mensaje_en_espera" in acciones
    assert "escalado" not in acciones, "no hay derivación nueva: ya estaba derivado"


async def test_el_mensaje_y_el_acuse_quedan_en_el_caso(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    """El operador tiene que ver lo que el vecino escribió y lo que se le
    contestó automáticamente, sin salir del caso."""
    caso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.consulta,
        estado=EstadoCaso.escalado,
        canal_origen=Canal.email,
        canal_actual=Canal.email,
    )
    db_session.add(caso)
    await db_session.commit()

    mock_llms(ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9))

    await procesar_mensaje(
        db_session,
        mensaje="¿Alguna novedad?",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=checkpointer_en_memoria,
    )

    interacciones = (
        (
            await db_session.execute(
                select(Interaccion)
                .where(Interaccion.caso_id == caso.id)
                .order_by(Interaccion.timestamp)
            )
        )
        .scalars()
        .all()
    )

    assert [i.actor for i in interacciones] == [
        ActorInteraccion.ciudadano,
        ActorInteraccion.agente_ia,
    ]
    assert interacciones[0].contenido == "¿Alguna novedad?"
    assert "en manos de una persona" in interacciones[1].contenido


async def test_el_caso_tomado_por_un_operador_tampoco_lo_retoma_el_agente(
    db_session, ciudadano, usuario_operador, mock_llms, checkpointer_en_memoria
):
    caso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.reclamo,
        estado=EstadoCaso.en_progreso,
        operador_asignado_id=usuario_operador.id,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )
    db_session.add(caso)
    await db_session.commit()

    mock_llms(
        ClasificacionIntent(intencion="reclamo", entidades={}, confianza=0.95),
        respuestas_ejecutor=[AIMessage(content="no debería usarse")],
    )

    final = await procesar_mensaje(
        db_session,
        mensaje="Sigue sin arreglarse la vereda",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    assert final["respuesta"].endswith(mensaje_espera(caso.referencia))


async def test_la_cortesia_al_operador_queda_registrada_en_el_caso(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria, ventana_de_silencio
):
    """Reproducción exacta del caso real: caso derivado, el operador contesta y
    el ciudadano responde "OK, gracias por avisar". Ese mensaje tiene que quedar
    en el caso —el operador necesita saber que le contestaron— y no puede
    devolver el saludo genérico."""
    caso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.reclamo,
        estado=EstadoCaso.escalado,
        canal_origen=Canal.email,
        canal_actual=Canal.email,
    )
    db_session.add(caso)
    await db_session.flush()
    db_session.add(
        Interaccion(
            caso_id=caso.id,
            contenido="Le aviso que el pozo se repara mañana.",
            canal=Canal.email,
            actor=ActorInteraccion.operador,
            timestamp=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    await db_session.commit()

    mock_llms(
        ClasificacionIntent(
            intencion="saludo", entidades={}, confianza=0.95, continua_caso_abierto=False
        )
    )

    final = await procesar_mensaje(
        db_session,
        mensaje="OK, gracias por avisar.",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=checkpointer_en_memoria,
    )

    assert final["caso_id"] == str(caso.id)
    # El operador acaba de escribirle: el agente no se mete. Lo importante es
    # que el "gracias" igual quede en el caso y que no reciba el saludo
    # genérico ofreciéndole tomar un reclamo.
    assert final["respuesta"] is None

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
    assert "OK, gracias por avisar." in contenidos, "el mensaje no puede perderse"

    casos = (
        (await db_session.execute(select(Caso).where(Caso.ciudadano_id == ciudadano.id)))
        .scalars()
        .all()
    )
    assert len(casos) == 1


async def test_no_repite_el_acuse_si_recien_le_avisaron(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria, ventana_de_silencio
):
    """Insistir a los dos minutos de "lo van a contactar" no merece que se lo
    repitan: el agente se calla, pero el mensaje igual queda en el caso."""
    caso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.tramite,
        estado=EstadoCaso.escalado,
        canal_origen=Canal.email,
        canal_actual=Canal.email,
    )
    db_session.add(caso)
    await db_session.flush()
    db_session.add(
        Interaccion(
            caso_id=caso.id,
            contenido="Lo van a contactar por este mismo medio.",
            canal=Canal.email,
            actor=ActorInteraccion.agente_ia,
            timestamp=datetime.now(timezone.utc) - timedelta(minutes=2),
        )
    )
    await db_session.commit()

    mock_llms(ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9))

    final = await procesar_mensaje(
        db_session,
        mensaje="¿Hay alguna novedad?",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=checkpointer_en_memoria,
    )

    assert final["respuesta"] is None, "no le contesta nada"

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
    assert "¿Hay alguna novedad?" in contenidos, "el mensaje no puede perderse"


async def test_vuelve_a_acusar_recibo_cuando_ya_paso_un_rato(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria, ventana_de_silencio
):
    """Si hace horas que nadie le contesta, el silencio se lee como abandono."""
    caso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.tramite,
        estado=EstadoCaso.escalado,
        canal_origen=Canal.email,
        canal_actual=Canal.email,
    )
    db_session.add(caso)
    await db_session.flush()
    db_session.add(
        Interaccion(
            caso_id=caso.id,
            contenido="Lo van a contactar por este mismo medio.",
            canal=Canal.email,
            actor=ActorInteraccion.agente_ia,
            timestamp=datetime.now(timezone.utc) - timedelta(hours=5),
        )
    )
    await db_session.commit()

    mock_llms(ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9))

    final = await procesar_mensaje(
        db_session,
        mensaje="¿Hay alguna novedad?",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=checkpointer_en_memoria,
    )

    assert final["respuesta"].endswith(mensaje_espera(caso.referencia))


async def test_acusa_recibo_si_el_aviso_salio_por_otro_canal(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria, ventana_de_silencio
):
    """El bug de la demo: pidió una persona por teléfono y a los cinco minutos
    escribió por otro canal. El aviso de la derivación lo escuchó en la llamada,
    no lo leyó en este chat, y el agente se callaba igual: la ventana miraba lo
    último que salió por cualquier canal."""
    caso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.reclamo,
        estado=EstadoCaso.en_progreso,
        canal_origen=Canal.email,
        canal_actual=Canal.voz,
    )
    db_session.add(caso)
    await db_session.flush()
    db_session.add(
        Interaccion(
            caso_id=caso.id,
            contenido="Lo pongo en contacto con una persona del equipo.",
            canal=Canal.voz,
            actor=ActorInteraccion.agente_ia,
            timestamp=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )
    await db_session.commit()

    mock_llms([ClasificacionIntent(intencion="consulta", entidades={}, confianza=0.9)] * 2)

    primero = await procesar_mensaje(
        db_session,
        mensaje="hola",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=checkpointer_en_memoria,
    )
    assert primero["respuesta"].endswith(mensaje_espera(caso.referencia)), (
        "en este canal nunca vio el aviso: se le acusa recibo"
    )

    # El acuse ya salió por este canal: insistir enseguida no lo repite.
    segundo = await procesar_mensaje(
        db_session,
        mensaje="hola?",
        canal=Canal.email,
        identificador=ciudadano.email,
        checkpointer=checkpointer_en_memoria,
    )
    assert segundo["respuesta"] is None


async def test_un_tema_nuevo_no_se_lo_queda_el_caso_derivado(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria
):
    """El ciudadano tiene un reclamo derivado y aparte pregunta otra cosa. Esa
    consulta la puede resolver el agente: acusarle recibo del reclamo derivado
    es contestarle cualquier cosa."""
    derivado = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.reclamo,
        estado=EstadoCaso.escalado,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )
    db_session.add(derivado)
    await db_session.commit()

    mock_llms(
        ClasificacionIntent(
            intencion="consulta", entidades={}, confianza=0.95, continua_caso_abierto=False
        ),
        respuestas_ejecutor=[AIMessage(content="Atendemos de 8 a 14, de lunes a viernes.")],
    )

    final = await procesar_mensaje(
        db_session,
        mensaje="Aparte de eso, ¿qué horario tienen para atender?",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    assert final["respuesta"].endswith("Atendemos de 8 a 14, de lunes a viernes.")
    assert final["caso_id"] != str(derivado.id), "no se cuelga del caso del operador"

    await db_session.refresh(derivado)
    assert derivado.estado == EstadoCaso.escalado


async def test_un_hola_mucho_despues_arranca_conversacion_nueva(
    db_session, ciudadano, mock_llms, checkpointer_en_memoria, ventana_de_silencio
):
    """La contracara del test anterior. Un caso derivado que nadie tomó no puede
    quedarse con todos los saludos futuros: si un "hola" de la semana siguiente
    cae en ese caso, el ciudadano no vuelve a hablar con el agente nunca más."""
    derivado = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.reclamo,
        estado=EstadoCaso.escalado,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
    )
    db_session.add(derivado)
    await db_session.flush()
    db_session.add(
        Interaccion(
            caso_id=derivado.id,
            contenido="Lo van a contactar por este mismo medio.",
            canal=Canal.whatsapp,
            actor=ActorInteraccion.agente_ia,
            timestamp=datetime.now(timezone.utc) - timedelta(days=3),
        )
    )
    await db_session.commit()

    mock_llms(
        # El intake puede decir que continúa el caso: para una cortesía manda el
        # tiempo, no lo que opine el clasificador.
        ClasificacionIntent(
            intencion="saludo", entidades={}, confianza=1.0, continua_caso_abierto=True
        )
    )

    final = await procesar_mensaje(
        db_session,
        mensaje="Hola",
        canal=Canal.whatsapp,
        identificador=ciudadano.telefono,
        checkpointer=checkpointer_en_memoria,
    )

    # Es el saludo con el menú, no el acuse de recibo del caso derivado. Y le
    # ofrece retomarlo, que es distinto de metérselo por la fuerza.
    assert MENU in final["respuesta"]
    assert derivado.referencia in final["respuesta"]
    assert final["caso_id"] is None

    interacciones = (
        (
            await db_session.execute(
                select(Interaccion).where(
                    Interaccion.caso_id == derivado.id,
                    Interaccion.contenido == "Hola",
                )
            )
        )
        .scalars()
        .all()
    )
    assert interacciones == [], "el saludo no se cuelga del caso del operador"
