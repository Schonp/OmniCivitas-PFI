import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models import (
    ActorInteraccion,
    Auditoria,
    Canal,
    Caso,
    EstadoCaso,
    Interaccion,
    TipoCaso,
)

BASE = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)


async def _armar_escenario(db_session, ciudadano):
    """Dos casos: uno resuelto por la IA con cambio de canal, otro escalado."""
    automatizado = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.reclamo,
        estado=EstadoCaso.cerrado,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.email,
    )
    escalado = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.tramite,
        estado=EstadoCaso.escalado,
        canal_origen=Canal.email,
        canal_actual=Canal.email,
    )
    db_session.add_all([automatizado, escalado])
    await db_session.flush()

    db_session.add_all(
        [
            Interaccion(
                caso_id=automatizado.id,
                contenido="Consulta inicial",
                canal=Canal.whatsapp,
                actor=ActorInteraccion.ciudadano,
                timestamp=BASE,
            ),
            Interaccion(
                caso_id=automatizado.id,
                contenido="Respuesta del agente",
                canal=Canal.whatsapp,
                actor=ActorInteraccion.agente_ia,
                timestamp=BASE + timedelta(minutes=4),
            ),
            Auditoria(
                caso_id=automatizado.id,
                accion="respuesta_ia",
                actor="agente_ia",
                actor_tipo=ActorInteraccion.agente_ia,
                metadata_={"confianza": 0.9},
            ),
            Auditoria(
                caso_id=automatizado.id,
                accion="cambio_canal",
                actor="agente_ia",
                actor_tipo=ActorInteraccion.agente_ia,
                metadata_={"canal_anterior": "whatsapp", "canal_nuevo": "email"},
            ),
            Auditoria(
                caso_id=escalado.id,
                accion="escalado",
                actor="agente_ia",
                actor_tipo=ActorInteraccion.agente_ia,
                metadata_={"motivo": "confianza_baja"},
            ),
            Auditoria(
                caso_id=escalado.id,
                accion="respuesta_ia",
                actor="agente_ia",
                actor_tipo=ActorInteraccion.agente_ia,
                metadata_={"confianza": 0.5},
            ),
        ]
    )
    await db_session.commit()


async def test_metricas_requieren_auth(client):
    response = await client.get("/api/metricas")
    assert response.status_code == 401


async def test_metricas_sin_casos_no_divide_por_cero(client, auth_headers):
    response = await client.get("/api/metricas", headers=auth_headers)

    assert response.status_code == 200
    cuerpo = response.json()
    assert cuerpo["total_casos"] == 0
    assert cuerpo["tasa_automatizacion"] is None
    assert cuerpo["minutos_primera_respuesta"] is None
    assert cuerpo["confianza_promedio"] is None


async def test_metricas_agrega_por_dimension(client, db_session, auth_headers, ciudadano):
    await _armar_escenario(db_session, ciudadano)

    response = await client.get("/api/metricas", headers=auth_headers)

    assert response.status_code == 200
    cuerpo = response.json()
    assert cuerpo["total_casos"] == 2
    assert cuerpo["por_canal"] == {"email": 2}
    assert cuerpo["por_tipo"] == {"reclamo": 1, "tramite": 1}
    assert cuerpo["por_estado"] == {"cerrado": 1, "escalado": 1}


async def test_metricas_calcula_automatizacion_y_continuidad(
    client, db_session, auth_headers, ciudadano
):
    await _armar_escenario(db_session, ciudadano)

    cuerpo = (await client.get("/api/metricas", headers=auth_headers)).json()

    assert cuerpo["escalados"] == 1
    assert cuerpo["resueltos_por_ia"] == 1
    assert cuerpo["tasa_automatizacion"] == 0.5
    assert cuerpo["casos_con_cambio_canal"] == 1
    assert cuerpo["minutos_primera_respuesta"] == 4.0
    assert cuerpo["confianza_promedio"] == 0.7


async def test_metricas_serie_diaria_cubre_14_dias_sin_huecos(
    client, db_session, auth_headers, ciudadano
):
    await _armar_escenario(db_session, ciudadano)

    cuerpo = (await client.get("/api/metricas", headers=auth_headers)).json()

    serie = cuerpo["casos_por_dia"]
    assert len(serie) == 14
    # Los dos casos del escenario se crean hoy; el resto de los días queda en cero.
    assert serie[-1]["casos"] == 2
    assert sum(dia["casos"] for dia in serie) == 2


async def test_metricas_del_operador_solo_cuentan_su_bandeja(
    client, db_session, headers_operador, usuario_operador, ciudadano
):
    """El escenario tiene 2 casos; al operador se le asigna solo el escalado,
    así que sus métricas no ven el caso automatizado del resto del organismo."""
    await _armar_escenario(db_session, ciudadano)
    escalado = (
        await db_session.execute(select(Caso).where(Caso.estado == EstadoCaso.escalado))
    ).scalars().first()
    escalado.operador_asignado_id = usuario_operador.id
    await db_session.commit()

    cuerpo = (await client.get("/api/metricas", headers=headers_operador)).json()

    assert cuerpo["total_casos"] == 1
    assert cuerpo["por_estado"] == {"escalado": 1}
    assert cuerpo["escalados"] == 1
    assert cuerpo["resueltos_por_ia"] == 0
    # La primera respuesta y el cambio de canal ocurrieron en el caso ajeno.
    assert cuerpo["minutos_primera_respuesta"] is None
    assert cuerpo["casos_con_cambio_canal"] == 0
    assert cuerpo["confianza_promedio"] == 0.5


async def test_metricas_cuenta_escalado_aunque_el_caso_este_cerrado(
    client, db_session, auth_headers, ciudadano
):
    """La verdad la tiene la auditoría: un caso escalado y luego cerrado siguió
    necesitando a un humano, así que no cuenta como automatizado."""
    caso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.consulta,
        estado=EstadoCaso.cerrado,
        canal_origen=Canal.email,
        canal_actual=Canal.email,
    )
    db_session.add(caso)
    await db_session.flush()
    db_session.add(
        Auditoria(
            caso_id=caso.id,
            accion="escalado",
            actor="agente_ia",
            actor_tipo=ActorInteraccion.agente_ia,
            metadata_={"motivo": "requiere_humano"},
        )
    )
    await db_session.commit()

    cuerpo = (await client.get("/api/metricas", headers=auth_headers)).json()

    assert cuerpo["escalados"] == 1
    assert cuerpo["resueltos_por_ia"] == 0
    assert cuerpo["tasa_automatizacion"] == 0.0
