"""Carga datos de demostración para el panel de operador.

Genera casos, interacciones y auditoría sin llamar al LLM, para poder tomar
capturas del panel aunque Ollama no esté corriendo.

Uso:  python -m scripts.seed_demo
"""

import asyncio
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import (
    ActorInteraccion,
    Auditoria,
    Canal,
    Caso,
    Ciudadano,
    DocumentoConocimiento,
    EstadoCaso,
    EstadoReserva,
    GrupoReclamo,
    Interaccion,
    Reserva,
    RolUsuario,
    TipoCaso,
    Turno,
    Usuario,
)
from app.db.crud.turnos import ZONA_HORARIA, horarios_del_dia
from app.db.session import async_session_factory

SUPERVISOR_DEMO = "supervisor@omnicivitas.test"
PASSWORD_SUPERVISOR = "supervisor123"
OPERADOR_DEMO = "operador@omnicivitas.test"
PASSWORD_OPERADOR = "operador123"
ACTOR_AGENTE = "agente_ia"

AHORA = datetime.now(timezone.utc)


def hace(horas: float) -> datetime:
    return AHORA - timedelta(hours=horas)


async def _crear_usuarios_demo(db) -> Usuario:
    """Un supervisor y un operador, para poder mostrar la diferencia de rol."""
    cuentas = [
        (SUPERVISOR_DEMO, "Marta Ruiz", PASSWORD_SUPERVISOR, RolUsuario.supervisor),
        (OPERADOR_DEMO, "Diego Ferreyra", PASSWORD_OPERADOR, RolUsuario.operador),
    ]
    creados: dict[str, Usuario] = {}

    for email, nombre, password, rol in cuentas:
        usuario = (
            await db.execute(select(Usuario).where(Usuario.email == email))
        ).scalars().first()
        if usuario is None:
            usuario = Usuario(
                email=email,
                nombre=nombre,
                hashed_password=hash_password(password),
                rol=rol,
            )
            db.add(usuario)
            await db.flush()
        creados[email] = usuario

    return creados[OPERADOR_DEMO]


async def _caso_reclamo_cross_canal(db, operador: Usuario) -> None:
    """El caso testigo de la tesis: nace en WhatsApp y sigue por correo electrónico."""
    ciudadana = Ciudadano(
        documento="28456789",
        nombre="María López",
        email="maria.lopez@demo.test",
        telefono="+5491133344455",
    )
    db.add(ciudadana)
    await db.flush()

    caso = Caso(
        ciudadano_id=ciudadana.id,
        tipo=TipoCaso.reclamo,
        estado=EstadoCaso.en_progreso,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.email,
        operador_asignado_id=operador.id,
        created_at=hace(52),
        updated_at=hace(3),
    )
    db.add(caso)
    await db.flush()

    conversacion = [
        (hace(52), Canal.whatsapp, ActorInteraccion.ciudadano,
         "Hola, hace más de una semana que no pasa el camión de basura por Av. Rivadavia al 4500."),
        (hace(51.9), Canal.whatsapp, ActorInteraccion.agente_ia,
         "Buen día. Registré su reclamo por falta de recolección con el número "
         "REC-1042. El área de Higiene Urbana tiene 72 horas hábiles para responder."),
        (hace(4), Canal.email, ActorInteraccion.ciudadano,
         "Buenas, quería saber cómo viene el reclamo que hice por WhatsApp."),
        (hace(3.9), Canal.email, ActorInteraccion.agente_ia,
         "Su reclamo REC-1042 por falta de recolección está en progreso: fue "
         "derivado a Higiene Urbana el martes. No necesita volver a cargarlo."),
        (hace(3), Canal.email, ActorInteraccion.operador,
         "Confirmo que el camión pasa mañana por la mañana. Dejo el caso en seguimiento."),
    ]
    for momento, canal, actor, contenido in conversacion:
        db.add(
            Interaccion(
                caso_id=caso.id, contenido=contenido, canal=canal, actor=actor, timestamp=momento
            )
        )

    registros = [
        (hace(52), "creacion_reclamo", ACTOR_AGENTE, ActorInteraccion.agente_ia,
         {"categoria": "servicio", "intencion": "reclamo", "confianza": 0.92}),
        (hace(51.9), "respuesta_ia", ACTOR_AGENTE, ActorInteraccion.agente_ia,
         {"intencion": "reclamo", "confianza": 0.92, "escalado": False}),
        (hace(3.9), "cambio_canal", ACTOR_AGENTE, ActorInteraccion.agente_ia,
         {"canal_anterior": "whatsapp", "canal_nuevo": "email"}),
        (hace(3.9), "respuesta_ia", ACTOR_AGENTE, ActorInteraccion.agente_ia,
         {"intencion": "consulta", "confianza": 0.88, "escalado": False}),
        (hace(3), "cambio_estado", SUPERVISOR_DEMO, ActorInteraccion.operador,
         {"estado_anterior": "abierto", "estado_nuevo": "en_progreso"}),
    ]
    for momento, accion, actor, actor_tipo, metadata in registros:
        db.add(
            Auditoria(
                caso_id=caso.id,
                accion=accion,
                actor=actor,
                actor_tipo=actor_tipo,
                timestamp=momento,
                metadata_=metadata,
            )
        )


async def _caso_consulta_resuelta(db) -> None:
    ciudadano = Ciudadano(
        documento="33987654",
        nombre="Jorge Pereyra",
        email="jorge.pereyra@demo.test",
        telefono="+5491144455566",
    )
    db.add(ciudadano)
    await db.flush()

    caso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.consulta,
        estado=EstadoCaso.cerrado,
        canal_origen=Canal.email,
        canal_actual=Canal.email,
        created_at=hace(28),
        updated_at=hace(26),
    )
    db.add(caso)
    await db.flush()

    db.add_all(
        [
            Interaccion(
                caso_id=caso.id,
                contenido="Buenas tardes, ¿qué documentación necesito para habilitar un "
                "local gastronómico?",
                canal=Canal.email,
                actor=ActorInteraccion.ciudadano,
                timestamp=hace(28),
            ),
            Interaccion(
                caso_id=caso.id,
                contenido="Necesita el certificado de uso conforme, el plano del local "
                "firmado por profesional matriculado y la libreta sanitaria del personal. "
                "El trámite se inicia en la sede comunal que le corresponda.",
                canal=Canal.email,
                actor=ActorInteraccion.agente_ia,
                timestamp=hace(27.9),
            ),
        ]
    )
    db.add_all(
        [
            Auditoria(
                caso_id=caso.id,
                accion="respuesta_ia",
                actor=ACTOR_AGENTE,
                actor_tipo=ActorInteraccion.agente_ia,
                timestamp=hace(27.9),
                metadata_={"intencion": "consulta", "confianza": 0.95, "escalado": False},
            ),
            Auditoria(
                caso_id=caso.id,
                accion="cambio_estado",
                actor=OPERADOR_DEMO,
                actor_tipo=ActorInteraccion.operador,
                timestamp=hace(26),
                metadata_={"estado_anterior": "abierto", "estado_nuevo": "cerrado"},
            ),
        ]
    )


async def _caso_escalado(db) -> None:
    ciudadana = Ciudadano(
        documento="41222333",
        nombre="Silvia Ramos",
        email="silvia.ramos@demo.test",
        telefono="+5491155566677",
    )
    db.add(ciudadana)
    await db.flush()

    caso = Caso(
        ciudadano_id=ciudadana.id,
        tipo=TipoCaso.tramite,
        estado=EstadoCaso.escalado,
        canal_origen=Canal.email,
        canal_actual=Canal.email,
        created_at=hace(6),
        updated_at=hace(6),
    )
    db.add(caso)
    await db.flush()

    db.add_all(
        [
            Interaccion(
                caso_id=caso.id,
                contenido="Necesito presentar una denuncia por un problema con una "
                "inspección que me hicieron, tengo documentación para adjuntar.",
                canal=Canal.email,
                actor=ActorInteraccion.ciudadano,
                timestamp=hace(6),
            ),
            Interaccion(
                caso_id=caso.id,
                contenido="Su solicitud fue derivada a un operador, que lo contactará a "
                "la brevedad por este mismo medio. Gracias por comunicarse.",
                canal=Canal.email,
                actor=ActorInteraccion.agente_ia,
                timestamp=hace(5.95),
            ),
        ]
    )
    db.add(
        Auditoria(
            caso_id=caso.id,
            accion="escalado",
            actor=ACTOR_AGENTE,
            actor_tipo=ActorInteraccion.agente_ia,
            timestamp=hace(5.95),
            metadata_={
                "motivo": "requiere_humano",
                "resumen": "La ciudadana quiere presentar una denuncia formal por una "
                "inspección y tiene documentación para adjuntar. Requiere intervención "
                "de un operador con acceso al expediente.",
            },
        )
    )


async def _caso_reserva_abierta(db) -> None:
    ciudadano = Ciudadano(
        documento="25111444",
        nombre="Diego Fernández",
        email="diego.fernandez@demo.test",
        telefono="+5491166677788",
    )
    db.add(ciudadano)
    await db.flush()

    caso = Caso(
        ciudadano_id=ciudadano.id,
        tipo=TipoCaso.reserva,
        estado=EstadoCaso.abierto,
        canal_origen=Canal.whatsapp,
        canal_actual=Canal.whatsapp,
        created_at=hace(34),
        updated_at=hace(30),
    )
    db.add(caso)
    await db.flush()

    db.add_all(
        [
            Interaccion(
                caso_id=caso.id,
                contenido="Quiero sacar un turno para renovar la licencia de conducir "
                "la semana que viene.",
                canal=Canal.whatsapp,
                actor=ActorInteraccion.ciudadano,
                timestamp=hace(34),
            ),
            Interaccion(
                caso_id=caso.id,
                contenido="Registré su solicitud de turno para renovación de licencia. "
                "Le vamos a confirmar día y hora por este mismo canal.",
                canal=Canal.whatsapp,
                actor=ActorInteraccion.agente_ia,
                timestamp=hace(33.9),
            ),
            # Repregunta sin responder: es la que dispara el resaltado de demora
            # y la métrica de casos esperando respuesta.
            Interaccion(
                caso_id=caso.id,
                contenido="Perdón, ¿el turno me lo confirman por acá o me llaman?",
                canal=Canal.whatsapp,
                actor=ActorInteraccion.ciudadano,
                timestamp=hace(30),
            ),
        ]
    )
    db.add(
        Auditoria(
            caso_id=caso.id,
            accion="creacion_reserva",
            actor=ACTOR_AGENTE,
            actor_tipo=ActorInteraccion.agente_ia,
            timestamp=hace(34),
            metadata_={"intencion": "reserva", "confianza": 0.9},
        )
    )


# (nombre, descripción, sede, apertura, cierre, minutos por turno, cupos por horario)
TURNOS_DEMO = [
    (
        "Renovación de licencia de conducir",
        "Turnos para renovar la licencia de conducir en la sede comunal. "
        "Requiere licencia anterior, DNI y el pago de la boleta previa.",
        "Sede comunal, mesa de licencias",
        time(8, 0), time(14, 0), 30, 1,
    ),
    (
        "Renovación de DNI",
        "Turnos para tramitar la renovación del DNI en el centro de documentación "
        "más cercano al domicilio.",
        "Centro de documentación de la sede comunal",
        time(8, 0), time(13, 0), 20, 2,
    ),
    (
        "Atención en centro de salud (CeSAC)",
        "Turnos de atención primaria en los centros de salud y acción comunitaria.",
        "Centro de salud del barrio",
        time(9, 0), time(15, 0), 30, 2,
    ),
]

# Vecinos con turno en la semana, para que la grilla del panel se vea como la
# de un organismo en funcionamiento y no vacía. Los nombres se combinan.
NOMBRES = ["Lucía", "Martín", "Sofía", "Diego", "Valentina", "Tomás", "Camila", "Nicolás",
           "Julieta", "Federico", "Agustina", "Pablo", "Florencia", "Gonzalo", "Micaela"]
APELLIDOS = ["Fernández", "Acosta", "Benítez", "Ramírez", "Sosa", "Herrera", "Torres", "Romero",
             "Molina", "Ruiz", "Díaz", "Medina", "Castro", "Suárez", "Giménez"]
PRIMER_DOCUMENTO_DE_LA_AGENDA = 30_555_100


async def _turnos_demo(db) -> dict[str, Turno]:
    """Las tres agendas de turnos comunes sobre las que reserva el agente."""
    turnos: dict[str, Turno] = {}
    for nombre, descripcion, sede, apertura, cierre, minutos, cupos in TURNOS_DEMO:
        turno = (
            await db.execute(select(Turno).where(Turno.nombre == nombre))
        ).scalars().first()
        if turno is None:
            turno = Turno(nombre=nombre, descripcion=descripcion)
            db.add(turno)
        # La grilla se actualiza también en una base ya sembrada.
        turno.sede = sede
        turno.dias_atencion = "0,1,2,3,4"
        turno.hora_apertura, turno.hora_cierre = apertura, cierre
        turno.duracion_minutos, turno.cupos_por_horario = minutos, cupos
        await db.flush()
        turnos[nombre] = turno
    return turnos


def _dias_habiles_desde(dia, cantidad: int) -> list:
    dias = []
    while len(dias) < cantidad:
        if dia.weekday() < 5:
            dias.append(dia)
        dia += timedelta(days=1)
    return dias


def _dias_habiles(cantidad: int) -> list:
    return _dias_habiles_desde(datetime.now(ZONA_HORARIA).date(), cantidad)


async def _agenda_de_la_semana(db, turnos: dict[str, Turno]) -> None:
    """Turnos repartidos en la semana en curso (completa) y en la siguiente
    (más liviana): lo que ya pasó queda atendido o ausente, y algunos
    cancelados. El reparto es fijo para que la demo sea reproducible."""
    if await _ciudadano_por_documento(db, str(PRIMER_DOCUMENTO_DE_LA_AGENDA)) is not None:
        return
    ahora = datetime.now(ZONA_HORARIA)
    lunes = ahora.date() - timedelta(days=ahora.weekday())
    dias = _dias_habiles_desde(lunes, 10)
    numero = 0
    for indice_agenda, agenda in enumerate(turnos.values()):
        for indice_dia, dia in enumerate(dias):
            grilla = horarios_del_dia(agenda, dia)
            por_dia = 4 if indice_dia < 5 else 2
            # Posiciones distintas: dos turnos en el mismo horario de una agenda
            # de un solo puesto la dejarían por encima de su cupo.
            posiciones = sorted({(k * 5 + indice_dia * 3 + indice_agenda * 2) % len(grilla) for k in range(por_dia)})
            for k, posicion in enumerate(posiciones):
                momento = grilla[posicion]
                # En las agendas con dos puestos, algunos horarios se llenan.
                veces = 2 if agenda.cupos_por_horario > 1 and k == 0 and indice_dia % 2 == 0 else 1
                for _ in range(veces):
                    numero += 1
                    await _turno_de_vecino(db, agenda, momento, numero, ahora)


async def _turno_de_vecino(db, agenda: Turno, momento: datetime, numero: int, ahora: datetime) -> None:
    nombre = f"{NOMBRES[numero % len(NOMBRES)]} {APELLIDOS[(numero * 7) % len(APELLIDOS)]}"
    vecino = Ciudadano(documento=str(PRIMER_DOCUMENTO_DE_LA_AGENDA + numero - 1), nombre=nombre)
    db.add(vecino)
    await db.flush()
    caso = Caso(
        ciudadano_id=vecino.id,
        tipo=TipoCaso.reserva,
        estado=EstadoCaso.cerrado,
        motivo_cierre="resuelto",
        canal_origen=Canal.whatsapp if numero % 3 else Canal.voz,
        canal_actual=Canal.whatsapp,
    )
    db.add(caso)
    await db.flush()
    hora = f"{momento.hour}:{momento.minute:02d}"
    db.add_all(
        [
            Interaccion(caso_id=caso.id, contenido=f"Quiero un turno de {agenda.nombre.lower()}",
                        canal=Canal.whatsapp, actor=ActorInteraccion.ciudadano),
            Interaccion(caso_id=caso.id,
                        contenido=f"Le reservé el turno de {agenda.nombre} a las {hora}.",
                        canal=Canal.whatsapp, actor=ActorInteraccion.agente_ia),
        ]
    )
    if momento < ahora:
        estado = EstadoReserva.ausente if numero % 6 == 0 else EstadoReserva.atendida
    elif numero % 9 == 0:
        estado = EstadoReserva.cancelada
    else:
        estado = EstadoReserva.confirmada
    db.add(
        Reserva(
            turno_id=agenda.id,
            caso_id=caso.id,
            ciudadano_id=vecino.id,
            fecha_hora=momento,
            estado=estado,
            motivo_cancelacion="Pedido del ciudadano" if estado == EstadoReserva.cancelada else None,
            cancelada_en=ahora if estado == EstadoReserva.cancelada else None,
        )
    )
    db.add(
        Auditoria(
            caso_id=caso.id,
            accion="creacion_reserva",
            actor=ACTOR_AGENTE,
            actor_tipo=ActorInteraccion.agente_ia,
            metadata_={"turno": agenda.nombre, "fecha_hora": momento.strftime("%Y-%m-%d %H:%M")},
        )
    )


async def _ciudadano_por_documento(db, documento: str) -> Ciudadano | None:
    return (
        await db.execute(select(Ciudadano).where(Ciudadano.documento == documento))
    ).scalars().first()


async def _reservas_demo(db, turnos: dict[str, Turno]) -> None:
    """Dos reservas hechas por el agente, para que la pantalla de turnos tenga
    material que verificar (la tercera agenda queda vacía a propósito)."""
    hay_reservas = (await db.execute(select(Reserva).limit(1))).scalars().first()
    if hay_reservas is not None:
        return

    ejemplos = [
        ("33987654", "Renovación de licencia de conducir",
         datetime.combine(_dias_habiles(3)[-1], time(10, 0), tzinfo=ZONA_HORARIA),
         "Necesito un turno para renovar la licencia de conducir, ¿puede ser el viernes a la mañana?",
         "Listo. Le reservé el turno de renovación de licencia de conducir para el "
         "viernes a las 10:00 en su sede comunal. Lleve la licencia anterior y el DNI."),
        ("28456789", "Renovación de DNI",
         datetime.combine(_dias_habiles(5)[-1], time(9, 40), tzinfo=ZONA_HORARIA),
         "Hola, quiero un turno para renovar mi DNI la semana que viene.",
         "Le reservé el turno de renovación de DNI para la semana próxima a las 09:30 "
         "en el centro de documentación de su comuna. Lleve el DNI anterior."),
    ]
    for documento, nombre_turno, fecha_hora, pedido, confirmacion in ejemplos:
        ciudadano = await _ciudadano_por_documento(db, documento)
        if ciudadano is None:
            continue

        caso = Caso(
            ciudadano_id=ciudadano.id,
            tipo=TipoCaso.reserva,
            estado=EstadoCaso.cerrado,
            motivo_cierre="resuelto",
            canal_origen=Canal.whatsapp,
            canal_actual=Canal.whatsapp,
            created_at=hace(10),
            updated_at=hace(9.8),
        )
        db.add(caso)
        await db.flush()

        db.add_all(
            [
                Interaccion(caso_id=caso.id, contenido=pedido, canal=Canal.whatsapp,
                            actor=ActorInteraccion.ciudadano, timestamp=hace(10)),
                Interaccion(caso_id=caso.id, contenido=confirmacion, canal=Canal.whatsapp,
                            actor=ActorInteraccion.agente_ia, timestamp=hace(9.9)),
            ]
        )
        db.add(
            Reserva(
                turno_id=turnos[nombre_turno].id,
                caso_id=caso.id,
                ciudadano_id=ciudadano.id,
                fecha_hora=fecha_hora,
            )
        )
        db.add(
            Auditoria(
                caso_id=caso.id,
                accion="creacion_reserva",
                actor=ACTOR_AGENTE,
                actor_tipo=ActorInteraccion.agente_ia,
                timestamp=hace(9.9),
                metadata_={"turno": nombre_turno,
                           "fecha_hora": fecha_hora.strftime("%Y-%m-%d %H:%M")},
            )
        )


async def _reclamo_comun_y_grupo(db) -> None:
    """Un segundo reclamo por el mismo problema que el de María, y la agrupación
    de la IA ya generada, para que la pantalla de reclamos en común tenga una
    foto sin depender de la API del LLM."""
    ya_existe = await _ciudadano_por_documento(db, "27888999")
    if ya_existe is not None:
        return

    vecino = Ciudadano(
        documento="27888999",
        nombre="Carlos Núñez",
        email="carlos.nunez@demo.test",
        telefono="+5491177788899",
    )
    db.add(vecino)
    await db.flush()

    caso = Caso(
        ciudadano_id=vecino.id,
        tipo=TipoCaso.reclamo,
        estado=EstadoCaso.abierto,
        canal_origen=Canal.email,
        canal_actual=Canal.email,
        created_at=hace(20),
        updated_at=hace(19.9),
    )
    db.add(caso)
    await db.flush()

    db.add_all(
        [
            Interaccion(
                caso_id=caso.id,
                contenido="Escribo porque hace días que no pasa el camión de basura por "
                "Av. Rivadavia al 4700. Se está acumulando en la esquina.",
                canal=Canal.email,
                actor=ActorInteraccion.ciudadano,
                timestamp=hace(20),
            ),
            Interaccion(
                caso_id=caso.id,
                contenido="Registré su reclamo por falta de recolección con el número "
                "REC-1055. El área de Higiene Urbana tiene 72 horas hábiles para responder.",
                canal=Canal.email,
                actor=ActorInteraccion.agente_ia,
                timestamp=hace(19.9),
            ),
        ]
    )
    db.add(
        Auditoria(
            caso_id=caso.id,
            accion="creacion_reclamo",
            actor=ACTOR_AGENTE,
            actor_tipo=ActorInteraccion.agente_ia,
            timestamp=hace(20),
            metadata_={"categoria": "servicio", "intencion": "reclamo", "confianza": 0.9},
        )
    )

    maria = await _ciudadano_por_documento(db, "28456789")
    if maria is not None:
        caso_maria = (
            await db.execute(
                select(Caso).where(
                    Caso.ciudadano_id == maria.id, Caso.tipo == TipoCaso.reclamo
                )
            )
        ).scalars().first()
        if caso_maria is not None:
            db.add(
                GrupoReclamo(
                    tema="Falta de recolección de residuos en Av. Rivadavia (Caballito)",
                    caso_ids=[str(caso_maria.id), str(caso.id)],
                )
            )


async def _conocimiento_demo(db) -> None:
    hay_documentos = (
        await db.execute(select(DocumentoConocimiento).limit(1))
    ).scalars().first()
    if hay_documentos is not None:
        return

    db.add_all(
        [
            DocumentoConocimiento(
                titulo="Requisitos para renovar la licencia de conducir",
                contenido="Para renovar la licencia de conducir necesita: licencia anterior, "
                "DNI vigente, pago de la boleta única (BUI) y el curso de educación vial "
                "aprobado si la licencia venció hace más de 90 días. El trámite se hace "
                "con turno previo en la sede comunal. La renovación tiene una vigencia "
                "de 5 años para menores de 65 años.",
            ),
            DocumentoConocimiento(
                titulo="Habilitación de locales gastronómicos",
                contenido="La habilitación de un local gastronómico requiere: certificado de "
                "uso conforme, plano del local firmado por profesional matriculado, libreta "
                "sanitaria del personal y constancia de desinfección vigente. El trámite se "
                "inicia en la sede comunal correspondiente al domicilio del local y demora "
                "aproximadamente 30 días hábiles.",
            ),
        ]
    )


async def main() -> None:
    async with async_session_factory() as db:
        ya_cargado = (
            await db.execute(select(Ciudadano).where(Ciudadano.documento == "28456789"))
        ).scalars().first()
        if ya_cargado is None:
            operador = await _crear_usuarios_demo(db)
            await _caso_reclamo_cross_canal(db, operador)
            await _caso_consulta_resuelta(db)
            await _caso_escalado(db)
            await _caso_reserva_abierta(db)

        # Cada sección nueva chequea por su cuenta: una base ya sembrada recibe
        # igual los turnos, las reservas, el grupo de reclamos y el conocimiento.
        turnos = await _turnos_demo(db)
        await _reservas_demo(db, turnos)
        await _agenda_de_la_semana(db, turnos)
        await _reclamo_comun_y_grupo(db)
        await _conocimiento_demo(db)
        await db.commit()

    print("Datos de demo cargados: casos, turnos, reservas, conocimiento y grupo de reclamos.")
    print(f"Supervisor (ve todo): {SUPERVISOR_DEMO} / {PASSWORD_SUPERVISOR}")
    print(f"Operador (solo su bandeja): {OPERADOR_DEMO} / {PASSWORD_OPERADOR}")


if __name__ == "__main__":
    asyncio.run(main())
