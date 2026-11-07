import uuid
from unittest.mock import AsyncMock, MagicMock

from app.agents.escalado import mensaje_escalado
from app.db.models import Canal


def test_mensaje_escalado_por_voz_avisa_que_el_seguimiento_es_por_whatsapp():
    """Todavía no hay operadores atendiendo por teléfono: una llamada
    derivada no puede decir "por este mismo medio" como en WhatsApp/email."""
    mensaje = mensaje_escalado("confianza_baja", "REC-ABC123", canal=Canal.voz)

    assert "WhatsApp" in mensaje
    assert "este mismo medio" not in mensaje
    assert "REC-ABC123" not in mensaje, "por llamada no se dicta el número de caso"


def test_mensaje_escalado_por_whatsapp_mantiene_el_mismo_medio():
    mensaje = mensaje_escalado("confianza_baja", "REC-ABC123", canal=Canal.whatsapp)

    assert "este mismo medio" in mensaje
    assert "WhatsApp" not in mensaje


async def test_el_motivo_refleja_la_causa_real_no_siempre_confianza_baja(db_session, mocker):
    """La auditoría llegaba a decir "confianza_baja" junto a una confianza de 0.85.
    Este test existe porque el arreglo ya se perdió una vez sin que nadie lo note."""
    from app.agents.escalado import _motivo_real

    base = {"confianza": 0.95, "intencion": "consulta", "ciudadano_id": "x"}

    assert _motivo_real({**base, "confianza": 0.2}) == "confianza_baja"
    assert _motivo_real({**base, "intencion": "tramite"}) == "sin_herramienta"
    assert _motivo_real({**base, "intencion": "otro"}) == "sin_herramienta"
    assert _motivo_real({**base, "ciudadano_id": None}) == "ciudadano_no_identificado"


async def test_al_escalar_el_resumen_queda_visible_en_el_caso(
    db_session, ciudadano, mocker
):
    """El operador tiene que ver de qué se trata sin leer el hilo entero."""
    from langchain_core.messages import AIMessage

    from app.agents.escalado import nodo_escalado
    from app.db.crud.casos import crear_caso
    from app.db.models import Canal, EstadoCaso, TipoCaso
    from app.schemas.caso import CasoCreate

    modelo = MagicMock()
    modelo.ainvoke = AsyncMock(return_value=AIMessage(content="El vecino pide datos censales."))
    mocker.patch("app.agents.llm.get_llm_intake", return_value=modelo)

    caso = await crear_caso(
        db_session,
        CasoCreate(
            ciudadano_id=ciudadano.id, tipo=TipoCaso.consulta, canal_origen=Canal.email
        ),
        actor="test",
    )
    await db_session.commit()

    await nodo_escalado(
        {
            "mensaje": "¿Cuántos habitantes tiene el municipio?",
            "canal": "email",
            "ciudadano_id": str(ciudadano.id),
            "caso_id": str(caso.id),
            "intencion": "consulta",
            "confianza": 0.95,
            "motivo_escalado": "sin_herramienta",
        },
        db_session,
    )

    await db_session.refresh(caso)
    assert caso.estado == EstadoCaso.escalado
    assert caso.resumen_ia == "El vecino pide datos censales."
    assert caso.resumen_ia_generado_en is not None


async def test_al_escalar_se_asigna_un_operador_automaticamente(
    db_session, ciudadano, mocker
):
    """El objetivo del feature: un caso escalado no se queda esperando a que
    un supervisor lo reparta a mano."""
    from langchain_core.messages import AIMessage

    from app.agents.escalado import nodo_escalado
    from app.core.security import hash_password
    from app.db.models import ActorInteraccion, Auditoria, Caso, EstadoCaso, RolUsuario, Usuario
    from sqlalchemy import select

    modelo = MagicMock()
    modelo.ainvoke = AsyncMock(return_value=AIMessage(content="Resumen"))
    mocker.patch("app.agents.llm.get_llm_intake", return_value=modelo)

    operador = Usuario(
        email="disponible@test.com", nombre="Disponible",
        hashed_password=hash_password("x"), rol=RolUsuario.operador,
    )
    db_session.add(operador)
    await db_session.commit()

    resultado = await nodo_escalado(
        {
            "mensaje": "Necesito ayuda con algo raro",
            "canal": "whatsapp",
            "ciudadano_id": str(ciudadano.id),
            "caso_id": None,
            "intencion": "otro",
            "confianza": 0.3,
            "motivo_escalado": None,
        },
        db_session,
    )

    caso = await db_session.get(Caso, uuid.UUID(resultado["caso_id"]))
    await db_session.refresh(caso)
    assert caso.operador_asignado_id == operador.id
    assert caso.estado == EstadoCaso.en_progreso, (
        "asignado automáticamente pasa a en_progreso, igual que si lo tomara a mano"
    )

    auditorias = (
        (await db_session.execute(select(Auditoria).where(Auditoria.caso_id == caso.id)))
        .scalars().all()
    )
    asignacion = next(a for a in auditorias if a.accion == "asignacion")
    assert asignacion.actor_tipo == ActorInteraccion.agente_ia, (
        "lo asignó el sistema, la auditoría no puede decir que fue un operador"
    )


async def test_sin_operadores_activos_el_caso_queda_como_antes(db_session, ciudadano, mocker):
    """Sin nadie a quien asignar, no rompe: se comporta como antes de este
    feature — escalado y sin asignar."""
    from langchain_core.messages import AIMessage

    from app.agents.escalado import nodo_escalado
    from app.db.models import Caso, EstadoCaso

    modelo = MagicMock()
    modelo.ainvoke = AsyncMock(return_value=AIMessage(content="Resumen"))
    mocker.patch("app.agents.llm.get_llm_intake", return_value=modelo)

    resultado = await nodo_escalado(
        {
            "mensaje": "Necesito ayuda con algo raro",
            "canal": "whatsapp",
            "ciudadano_id": str(ciudadano.id),
            "caso_id": None,
            "intencion": "otro",
            "confianza": 0.3,
            "motivo_escalado": None,
        },
        db_session,
    )

    caso = await db_session.get(Caso, uuid.UUID(resultado["caso_id"]))
    assert caso.operador_asignado_id is None
    assert caso.estado == EstadoCaso.escalado
