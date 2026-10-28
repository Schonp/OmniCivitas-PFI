"""Cancelación de turnos pedida por el ciudadano, y horario no disponible."""

import uuid
from datetime import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from app.agents import ejecutor as mod
from app.agents.cancelacion import pide_cancelar_turno
from app.agents.graph import decidir_ruta
from app.db.crud.turnos import reservar
from app.db.models import Canal, Caso, EstadoReserva, Reserva, TipoCaso, Turno
from tests.horarios import dia_habil, horario, momento


@pytest.mark.parametrize(
    "mensaje",
    [
        "Quiero cancelar mi turno",
        "Necesito anular la reserva del DNI",
        "No voy a poder ir al turno del jueves",
        "cancelo el RES-1A2B3C4D",
    ],
)
def test_reconoce_el_pedido_de_cancelar(mensaje):
    assert pide_cancelar_turno(mensaje)


@pytest.mark.parametrize(
    "mensaje", ["Quiero un turno para el DNI", "Cancelaron la recolección", "Hola"]
)
def test_no_confunde_otros_mensajes(mensaje):
    assert not pide_cancelar_turno(mensaje)


def test_el_pedido_de_cancelar_va_al_ejecutor_aunque_el_caso_este_con_una_persona():
    estado = {
        "mensaje": "Quiero cancelar mi turno",
        "ciudadano_id": str(uuid.uuid4()),
        "en_manos_humanas": True,
        "intencion": "tramite",
    }
    assert decidir_ruta(estado) == "ejecutor"


def _estado(ciudadano, mensaje: str, caso_id=None) -> dict:
    return {
        "mensaje": mensaje,
        "canal": "whatsapp",
        "identificador": ciudadano.telefono,
        "ciudadano_id": str(ciudadano.id),
        "identificado": True,
        "caso_id": caso_id,
        "historial": [],
        "conocimiento": [],
        "intencion": "reserva",
        "entidades": {},
        "confianza": 0.9,
        "resultado_ejecucion": None,
        "requiere_escalado": False,
        "motivo_escalado": None,
        "respuesta": None,
    }


async def _agenda_y_turno(db_session, ciudadano, nombre="Renovación de DNI", hora="10:00"):
    agenda = Turno(nombre=nombre, descripcion="Sede comunal.", hora_cierre=time(14, 0))
    db_session.add(agenda)
    caso = Caso(
        ciudadano_id=ciudadano.id, tipo=TipoCaso.reserva, canal_origen=Canal.whatsapp, canal_actual=Canal.whatsapp
    )
    db_session.add(caso)
    await db_session.flush()
    reserva = await reservar(
        db_session, agenda_id=agenda.id, ciudadano_id=ciudadano.id, caso_id=caso.id, momento=momento(hora=hora)
    )
    await db_session.commit()
    return agenda, caso, reserva


def _modelo_que_no_se_usa(mocker):
    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(side_effect=AssertionError("no hace falta el modelo"))
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)


async def test_cancela_el_unico_turno_y_libera_el_horario(db_session, ciudadano, mocker):
    _modelo_que_no_se_usa(mocker)
    _, caso, reserva = await _agenda_y_turno(db_session, ciudadano)

    resultado = await mod.nodo_ejecutor(_estado(ciudadano, "Quiero cancelar mi turno"), db_session)

    await db_session.refresh(reserva)
    assert reserva.estado == EstadoReserva.cancelada
    assert resultado["caso_id"] == str(caso.id)
    assert resultado["respuesta"].startswith("Listo, cancelé su turno de Renovación de DNI")
    assert caso.referencia in resultado["respuesta"]


async def test_con_dos_turnos_pregunta_cual(db_session, ciudadano, mocker):
    _modelo_que_no_se_usa(mocker)
    await _agenda_y_turno(db_session, ciudadano, "Renovación de DNI", "10:00")
    await _agenda_y_turno(db_session, ciudadano, "Licencia de conducir", "11:00")

    resultado = await mod.nodo_ejecutor(_estado(ciudadano, "Quiero cancelar mi turno"), db_session)

    assert "¿Cuál quiere cancelar?" in resultado["respuesta"]
    confirmadas = [r for r in (await db_session.execute(Reserva.__table__.select())).all() if r.estado == "confirmada"]
    assert len(confirmadas) == 2


async def test_con_dos_turnos_el_nombre_del_tramite_alcanza(db_session, ciudadano, mocker):
    _modelo_que_no_se_usa(mocker)
    await _agenda_y_turno(db_session, ciudadano, "Renovación de DNI", "10:00")
    _, _, licencia = await _agenda_y_turno(db_session, ciudadano, "Licencia de conducir", "11:00")

    resultado = await mod.nodo_ejecutor(
        _estado(ciudadano, "Quiero cancelar el turno de la licencia"), db_session
    )

    await db_session.refresh(licencia)
    assert licencia.estado == EstadoReserva.cancelada
    assert "Licencia de conducir" in resultado["respuesta"]


async def test_sin_turnos_pendientes_lo_dice(db_session, ciudadano, mocker):
    _modelo_que_no_se_usa(mocker)

    resultado = await mod.nodo_ejecutor(_estado(ciudadano, "Quiero cancelar mi turno"), db_session)

    assert resultado["respuesta"].startswith("No tiene turnos pendientes")


async def test_horario_ocupado_ofrece_los_libres_sin_el_modelo(db_session, ciudadano, mocker):
    """El modelo pide un horario ocupado: la respuesta trae horarios reales, no
    una segunda vuelta del modelo que podría inventarlos."""
    from app.db.models import Ciudadano

    agenda, _, _ = await _agenda_y_turno(db_session, ciudadano, hora="10:00")
    otra = Ciudadano(documento="27999888", nombre="Ana Gómez", telefono="+5491177778888")
    db_session.add(otra)
    await db_session.commit()

    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        return_value=AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "crear_reserva",
                    "args": {"turno": agenda.nombre, "fecha_hora": horario(hora="10:00")},
                    "id": "t1",
                }
            ],
        )
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    resultado = await mod.nodo_ejecutor(
        {**_estado(otra, f"El {dia_habil().day}/{dia_habil().month} a las 10"), "identificador": otra.telefono},
        db_session,
    )

    assert resultado["respuesta"].startswith("Ese horario ya está completo.")
    assert "Los horarios libres más cercanos son:" in resultado["respuesta"]
    assert resultado.get("requiere_escalado") is not True
    assert modelo.bind_tools.return_value.ainvoke.await_count == 1
    # Y no quedó un caso de reserva huérfano por el intento fallido.
    casos = (await db_session.execute(Caso.__table__.select().where(Caso.ciudadano_id == otra.id))).all()
    assert casos == []


def test_la_agenda_la_decide_lo_que_nombro_el_ciudadano():
    """Con el modelo real: pidió turno para la licencia y el modelo reservó en
    el centro de salud."""
    from app.agents.ejecutor import agenda_nombrada

    agendas = [
        Turno(nombre="Atención en centro de salud (CeSAC)", descripcion=""),
        Turno(nombre="Renovación de DNI", descripcion=""),
        Turno(nombre="Renovación de licencia de conducir", descripcion=""),
    ]
    assert agenda_nombrada(agendas, ["Quiero renovar la licencia"]).nombre.endswith("conducir")
    assert agenda_nombrada(agendas, ["turno para el DNI"]).nombre == "Renovación de DNI"
    assert agenda_nombrada(agendas, ["Quiero un turno"]) is None
    assert agenda_nombrada(agendas, ["el DNI y la licencia"]) is None


@pytest.mark.parametrize(
    ("dichos", "esperado"),
    [
        (["Laura Prueba, 30.111.298"], False),
        (["Quiero un turno para la licencia"], False),
        (["El jueves a las 9"], True),
        (["mañana a las 10"], True),
        (["el 5/11"], True),
        (["el 5 de noviembre"], True),
    ],
)
def test_reconoce_si_dijo_un_dia(dichos, esperado):
    from app.agents.ejecutor import dijo_un_dia

    assert dijo_un_dia(dichos) is esperado


async def test_sin_dia_dicho_no_reserva_y_lo_pregunta(db_session, ciudadano, mocker):
    """El modelo inventó una fecha que el ciudadano nunca dijo."""
    agenda = Turno(nombre="Renovación de licencia de conducir", descripcion="Sede.", hora_cierre=time(14, 0))
    db_session.add(agenda)
    await db_session.commit()
    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        return_value=AIMessage(
            content="",
            tool_calls=[{"name": "crear_reserva", "args": {"turno": "CeSAC", "fecha_hora": horario()}, "id": "t1"}],
        )
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    resultado = await mod.nodo_ejecutor(
        _estado(ciudadano, "Quiero un turno para renovar la licencia"), db_session
    )

    assert resultado["respuesta"].startswith("¿Qué día y a qué hora le queda bien?")
    assert "Renovación de licencia de conducir" in resultado["respuesta"]
    assert (await db_session.execute(Reserva.__table__.select())).all() == []


async def test_una_reserva_confirmada_en_el_texto_sin_hacerla_se_hace_de_verdad(
    db_session, ciudadano, mocker
):
    """Con el modelo real: "Le reservé el turno de Licencia de conducir por
    primera vez", sin ninguna herramienta y con una agenda que no existe."""
    from tests.horarios import dia_habil

    agenda = Turno(nombre="Renovación de licencia de conducir", descripcion="Sede.", hora_cierre=time(14, 0))
    db_session.add(agenda)
    await db_session.commit()
    dia = dia_habil(3)
    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        return_value=AIMessage(content="Le reservé el turno de Licencia de conducir por primera vez.")
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    resultado = await mod.nodo_ejecutor(
        _estado(ciudadano, f"Quiero turno para la licencia el {dia.day}/{dia.month} a las 10"), db_session
    )

    reservas = (await db_session.execute(Reserva.__table__.select())).all()
    assert len(reservas) == 1
    assert resultado["respuesta"].startswith("Le reservé el turno de Renovación de licencia de conducir.")


async def test_un_reclamo_confirmado_en_el_texto_sin_registrarlo_no_se_afirma(
    db_session, ciudadano, mocker
):
    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        return_value=AIMessage(content="Registré su reclamo por el bache. Número de caso: REC-12345678")
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    resultado = await mod.nodo_ejecutor(_estado(ciudadano, "Hay un bache"), db_session)

    assert resultado["respuesta"].startswith("Todavía no registré su reclamo.")


async def test_el_dia_que_dijo_el_ciudadano_manda_sobre_el_del_modelo(db_session, ciudadano, mocker):
    from tests.horarios import dia_habil

    agenda = Turno(nombre="Renovación de DNI", descripcion="Sede.", hora_cierre=time(14, 0))
    db_session.add(agenda)
    await db_session.commit()
    dia = dia_habil(3)
    otro_dia = dia_habil(6)
    modelo = MagicMock()
    modelo.bind_tools.return_value.ainvoke = AsyncMock(
        return_value=AIMessage(
            content="",
            tool_calls=[{"name": "crear_reserva", "args": {"turno": "Renovación de DNI",
                         "fecha_hora": f"{otro_dia.isoformat()} 11:00"}, "id": "t1"}],
        )
    )
    mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=modelo)

    await mod.nodo_ejecutor(_estado(ciudadano, f"Turno para el DNI el {dia.day}/{dia.month} a las 9:30"), db_session)

    reserva = (await db_session.execute(Reserva.__table__.select())).one()
    assert reserva.fecha_hora.astimezone(__import__("app.db.crud.turnos", fromlist=["x"]).ZONA_HORARIA).strftime("%Y-%m-%d %H:%M") == f"{dia.isoformat()} 09:30"
