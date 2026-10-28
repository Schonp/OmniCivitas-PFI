"""Cambio de horario de un turno pedido por el ciudadano."""

import uuid
from datetime import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents import ejecutor as mod
from app.agents.cancelacion import eleccion_de_horario_ofrecido, pide_cambiar_turno
from app.agents.confirmacion import MARCA_CAMBIO_NO_DISPONIBLE
from app.agents.graph import decidir_ruta
from app.db.crud.turnos import ZONA_HORARIA, reservar
from app.db.models import Canal, Caso, Ciudadano, Reserva, TipoCaso, Turno
from tests.horarios import dia_habil, momento


@pytest.mark.parametrize(
    "mensaje",
    ["Quiero cambiar mi turno para el viernes a las 10", "¿Me pasás el turno al lunes?", "mover la reserva"],
)
def test_reconoce_el_pedido_de_cambio(mensaje):
    assert pide_cambiar_turno(mensaje)


@pytest.mark.parametrize(
    "mensaje", ["Quiero un turno para cambiar el domicilio del DNI", "Cambiaron el horario de la recolección"]
)
def test_no_confunde_un_turno_nuevo_con_un_cambio(mensaje):
    assert not pide_cambiar_turno(mensaje)


async def _escenario(db_session, ciudadano):
    agenda = Turno(nombre="Renovación de licencia de conducir", descripcion="Sede.", hora_cierre=time(12, 0))
    db_session.add(agenda)
    caso = Caso(
        ciudadano_id=ciudadano.id, tipo=TipoCaso.reserva, canal_origen=Canal.whatsapp, canal_actual=Canal.whatsapp
    )
    db_session.add(caso)
    await db_session.flush()
    reserva = await reservar(
        db_session, agenda_id=agenda.id, ciudadano_id=ciudadano.id, caso_id=caso.id, momento=momento(hora="9:00")
    )
    await db_session.commit()
    return agenda, caso, reserva


def _estado(ciudadano, mensaje, historial=None):
    return {
        "mensaje": mensaje, "canal": "whatsapp", "identificador": ciudadano.telefono,
        "ciudadano_id": str(ciudadano.id), "identificado": True, "caso_id": None,
        "historial": historial or [], "conocimiento": [], "intencion": "reserva", "entidades": {},
        "confianza": 0.9, "resultado_ejecucion": None, "requiere_escalado": False,
        "motivo_escalado": None, "respuesta": None,
    }


def _sin_modelo(mocker):
    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(side_effect=AssertionError("no hace falta el modelo"))
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)


async def test_cambia_el_turno_al_horario_que_pide(db_session, ciudadano, mocker):
    _sin_modelo(mocker)
    _, caso, reserva = await _escenario(db_session, ciudadano)
    dia = dia_habil()

    resultado = await mod.nodo_ejecutor(
        _estado(ciudadano, f"Quiero cambiar mi turno para el {dia.day}/{dia.month} a las 11"), db_session
    )

    await db_session.refresh(reserva)
    assert reserva.fecha_hora.astimezone(ZONA_HORARIA).strftime("%H:%M") == "11:00"
    assert resultado["respuesta"].startswith("Listo, cambié su turno de Renovación de licencia de conducir.")
    assert resultado["caso_id"] == str(caso.id)


async def test_sin_horario_nuevo_lo_pregunta(db_session, ciudadano, mocker):
    _sin_modelo(mocker)
    await _escenario(db_session, ciudadano)

    resultado = await mod.nodo_ejecutor(_estado(ciudadano, "Quiero cambiar mi turno"), db_session)

    assert resultado["respuesta"].startswith("¿Para qué día y a qué hora quiere cambiar su turno")


async def test_horario_ocupado_ofrece_otros_y_entiende_la_respuesta_corta(db_session, ciudadano, mocker):
    _sin_modelo(mocker)
    agenda, caso, reserva = await _escenario(db_session, ciudadano)
    otra = Ciudadano(documento="27999888", nombre="Ana Gómez")
    db_session.add(otra)
    caso_otra = Caso(ciudadano_id=ciudadano.id, tipo=TipoCaso.reserva, canal_origen=Canal.voz, canal_actual=Canal.voz)
    db_session.add(caso_otra)
    await db_session.flush()
    caso_otra.ciudadano_id = otra.id
    await reservar(db_session, agenda_id=agenda.id, ciudadano_id=otra.id, caso_id=caso_otra.id, momento=momento(hora="10:00"))
    await db_session.commit()
    dia = dia_habil()

    oferta = await mod.nodo_ejecutor(
        _estado(ciudadano, f"Pasame el turno al {dia.day}/{dia.month} a las 10"), db_session
    )
    assert oferta["respuesta"].startswith(MARCA_CAMBIO_NO_DISPONIBLE)

    historial = [{"actor": "agente_ia", "contenido": oferta["respuesta"], "canal": "whatsapp"}]
    estado = _estado(ciudadano, "el de las 10:30", historial)
    assert decidir_ruta({**estado, "en_manos_humanas": False}) == "ejecutor"
    assert eleccion_de_horario_ofrecido(estado) is not None
    resultado = await mod.nodo_ejecutor(estado, db_session)

    await db_session.refresh(reserva)
    assert reserva.fecha_hora.astimezone(ZONA_HORARIA).strftime("%H:%M") == "10:30"
    assert resultado["respuesta"].startswith("Listo, cambié su turno")


async def test_si_ya_tiene_uno_del_tramite_le_dice_como_cambiarlo(db_session, ciudadano, mocker):
    from langchain_core.messages import AIMessage

    from tests.horarios import horario

    await _escenario(db_session, ciudadano)
    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        return_value=AIMessage(
            content="",
            tool_calls=[{"name": "crear_reserva", "args": {"turno": "licencia", "fecha_hora": horario(hora="11:00")}, "id": "t1"}],
        )
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)
    dia = dia_habil()

    resultado = await mod.nodo_ejecutor(
        _estado(ciudadano, f"Quiero otro turno para la licencia el {dia.day}/{dia.month} a las 11"), db_session
    )

    assert resultado["respuesta"].startswith("Ya tiene un turno de Renovación de licencia de conducir")
    assert '"cambiar mi turno al ' in resultado["respuesta"]
    assert len((await db_session.execute(Reserva.__table__.select())).all()) == 1
