"""Confirmación al ciudadano de una gestión que ya se ejecutó.

Cuando `crear_reclamo` o `crear_reserva` salen bien, el mensaje de cierre se
arma acá con los datos que devolvió la herramienta, en vez de pedírselo al
modelo en una segunda vuelta. El modelo local se ajustó con ejemplos de un solo
turno y nunca vio el resultado de una herramienta: en esa segunda vuelta
completaba con cosas que no pasaron ("ya quedó derivado", "le van a pedir el
comprobante"). Una confirmación con datos reales no puede inventar nada, y en
una llamada ahorra una inferencia entera antes de que el ciudadano escuche algo.
"""

from datetime import datetime, timedelta

from app.db.crud.turnos import ZONA_HORARIA, ahora_local, horario_de_atencion, momento_en_palabras
from app.db.models import Canal, Reserva, Turno
from app.tools.reservas import FORMATO_FECHA_HORA

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _descap(texto: str) -> str:
    texto = texto.strip().rstrip(".")
    return texto[0].lower() + texto[1:] if texto else texto


def dia_en_palabras(momento: datetime) -> str:
    """"martes 1 de diciembre"."""
    return f"{DIAS[momento.weekday()]} {momento.day} de {MESES[momento.month - 1]}"


def _fecha_legible(fecha_hora: str) -> tuple[str, str] | None:
    """("martes 1 de diciembre", "12:00") a partir de "2026-12-01 12:00"."""
    try:
        momento = datetime.strptime(fecha_hora, FORMATO_FECHA_HORA)
    except ValueError:
        return None
    return dia_en_palabras(momento), momento.strftime("%H:%M")


def _hora_hablada(hora: str) -> str:
    """"12:00" se dice "las 12"; "08:45" se dice "las 8:45"."""
    horas, minutos = hora.split(":")
    return f"las {int(horas)}" if minutos == "00" else f"las {int(horas)}:{minutos}"


def _reclamo(args: dict, salida: dict, voz: bool) -> str:
    descripcion = _descap(args.get("descripcion") or "")
    referencia = salida.get("referencia", "")
    sobre = f" por {descripcion}" if descripcion else ""
    if voz:
        # Sin el número de caso: "REC-0203E017" dicho en voz alta no se puede
        # anotar ni recordar, y alarga la respuesta. Para consultar después
        # alcanza con llamar desde el mismo número: el caso se busca por él.
        return (
            f"Listo, registré su reclamo{sobre}. "
            "Las novedades le van a llegar por WhatsApp a este mismo número."
        )
    return (
        f"Registré su reclamo{sobre}.\n\n"
        f"Número de caso: {referencia}\n\n"
        "Le vamos a avisar las novedades por este mismo medio."
    )


def _reserva(salida: dict, voz: bool) -> str:
    turno = salida.get("turno", "")
    referencia = salida.get("referencia", "")
    fecha = _fecha_legible(salida.get("fecha_hora", ""))
    sede = salida.get("sede")
    if voz:
        cuando = f" para el {fecha[0]} a {_hora_hablada(fecha[1])}" if fecha else ""
        donde = f", en {sede}" if sede else ""
        return f"Listo, le reservé el turno de {turno}{cuando}{donde}."
    lineas = [f"Le reservé el turno de {turno}.", "", f"Turno: {turno}"]
    if fecha:
        lineas.append(f"Día y hora: {fecha[0]}, {fecha[1]} h")
    if sede:
        lineas.append(f"Lugar: {sede}")
    lineas.append(f"Número de caso: {referencia}")
    lineas += ["", "Si no puede ir, escríbame \"cancelar mi turno\" y el horario queda libre para otra persona."]
    return "\n".join(lineas)


def confirmacion(nombre: str, args: dict, salida: dict, canal: Canal) -> str | None:
    """El mensaje de cierre para esa herramienta, o None si no tiene uno fijo
    (las consultas y la identificación las sigue redactando el modelo)."""
    voz = canal == Canal.voz
    if nombre == "crear_reclamo":
        return _reclamo(args, salida, voz)
    if nombre == "crear_reserva":
        return _reserva(salida, voz)
    return None


def pedido_de_identificacion(nombre: str, canal: Canal) -> str:
    """Lo que se le responde a quien todavía no informó su DNI cuando el modelo
    intenta crear un reclamo o una reserva a su nombre."""
    que = {"crear_reclamo": "su reclamo", "crear_reserva": "su pedido de turno"}.get(
        nombre, "su pedido"
    )
    if canal == Canal.voz:
        return (
            f"Tomé nota de {que}. Para gestionarlo a su nombre necesito su nombre "
            "completo y su número de documento. ¿Me los dice?"
        )
    return (
        f"Tomé nota de {que}. Para gestionarlo a su nombre necesito su nombre "
        "completo y su DNI.\n\n¿Me los indica?"
    )


# Marca del pedido de datos para buscar casos: en el turno siguiente, con el
# DNI, se contesta con el estado de sus casos (`_estado_al_sumar_contacto`).
MARCA_PEDIDO_PARA_CONSULTA = "Para buscar sus casos"


def pedido_de_identificacion_para_consulta(canal: Canal) -> str:
    """Quien pregunta por su caso desde un contacto que todavía no está a nombre
    de nadie: casi siempre lo inició por otro canal."""
    if canal == Canal.voz:
        return (
            f"{MARCA_PEDIDO_PARA_CONSULTA} necesito su nombre completo y su número de "
            "documento. ¿Me los dice?"
        )
    return f"{MARCA_PEDIDO_PARA_CONSULTA} necesito su nombre completo y su DNI.\n\n¿Me los indica?"


def agradecimiento(salida_identidad: dict) -> str:
    """Prefijo cuando el ciudadano se identificó en el mismo mensaje."""
    nombre = (salida_identidad.get("nombre") or "").split()
    return f"Gracias, {nombre[0].capitalize()}. " if nombre else "Gracias. "


TIPO_EN_PALABRAS = {
    "reclamo": "Su reclamo",
    "reserva": "Su turno",
    "consulta": "Su consulta",
    "tramite": "Su trámite",
}
ESTADO_EN_PALABRAS = {
    "abierto": "está registrado y pendiente de que el área lo tome",
    "en_progreso": "está en curso",
    "escalado": "lo está atendiendo una persona del equipo",
    "cerrado": "ya está cerrado",
}


def _de_que_trata(caso: dict) -> str:
    texto = _descap(caso.get("de_que_trata") or "")
    return texto if len(texto) <= 90 else texto[:87].rstrip() + "…"


def estado_de_casos(salida: dict, canal: Canal) -> str:
    """El estado de los casos que devolvió `consultar_estado_caso`, armado con
    los datos reales, para cuando no se le deja la respuesta al modelo."""
    voz = canal == Canal.voz
    if not salida.get("tiene_casos"):
        return "No encontré otros casos a su nombre. ¿En qué lo puedo ayudar?"
    if salida.get("varios_posibles"):
        casos = salida.get("casos") or []
        if voz:
            # Por voz se distinguen por de qué tratan, no por el número.
            temas = [f"uno por {_de_que_trata(c)}" for c in casos]
            lista = ", ".join(temas[:-1]) + " y " + temas[-1] if len(temas) > 1 else temas[0]
            return f"Tiene {len(casos)} casos a su nombre: {lista}. ¿Por cuál me consulta?"
        lineas = [f"- {c['referencia']}: {_de_que_trata(c)}" for c in casos]
        return "Encontré estos casos a su nombre:\n" + "\n".join(lineas) + "\n\n¿Por cuál me consulta?"
    tipo = TIPO_EN_PALABRAS.get(salida.get("tipo", ""), "Su caso")
    sobre = f" por {_de_que_trata(salida)}" if salida.get("de_que_trata") else ""
    estado = ESTADO_EN_PALABRAS.get(salida.get("estado", ""), "está registrado")
    referencia = salida.get("referencia", "")
    if voz:
        return f"{tipo}{sobre} {estado}."
    return f"{tipo}{sobre} {estado}.\n\nNúmero de caso: {referencia}"


def horario_no_disponible(
    motivo: str,
    alternativas: list,
    vigente: Reserva | None,
    canal: Canal,
    pedido: datetime | None = None,
) -> str:
    """Cuando el horario pedido no se puede reservar: por qué y qué hay libre."""
    voz = canal == Canal.voz
    if vigente is not None:
        # Ya tiene uno de ese trámite: se le dice cómo moverlo al que pidió.
        cuando = momento_en_palabras(pedido) if pedido else "otro día"
        return f"{motivo} Si quiere pasarlo al {cuando}, dígame \"cambiar mi turno al {cuando}\"."
    if not alternativas:
        return f"{motivo} No encontré horarios libres en los próximos días. ¿Quiere probar con otra fecha?"
    opciones = [momento_en_palabras(momento) for momento in alternativas]
    if voz:
        lista = ", ".join(opciones[:-1]) + (" o " if len(opciones) > 1 else "") + opciones[-1]
        return f"{motivo} Tengo libre el {lista}. ¿Cuál le queda mejor?"
    return (
        f"{motivo} Los horarios libres más cercanos son:\n"
        + "\n".join(f"- {opcion}" for opcion in opciones)
        + "\n\n¿Cuál le queda mejor?"
    )


def turno_cancelado(reserva: Reserva, canal: Canal) -> str:
    cuando = momento_en_palabras(reserva.fecha_hora)
    if canal == Canal.voz:
        return (
            f"Listo, cancelé su turno de {reserva.turno.nombre} del {cuando}. "
            "Si necesita otro, dígame qué día le queda bien."
        )
    return (
        f"Listo, cancelé su turno de {reserva.turno.nombre} del {cuando} "
        f"({reserva.caso.referencia}). El horario quedó libre.\n\n"
        "Si necesita otro turno, dígame qué día le queda bien."
    )


def turnos_para_elegir(reservas: list[Reserva], canal: Canal, cambiar: bool = False) -> str:
    accion = "cambiar" if cambiar else "cancelar"
    if canal == Canal.voz:
        lista = "; ".join(
            f"{r.turno.nombre} el {momento_en_palabras(r.fecha_hora)}" for r in reservas
        )
        return f"Tiene estos turnos pendientes: {lista}. ¿Cuál quiere {accion}?"
    lineas = [
        f"- {r.caso.referencia}: {r.turno.nombre}, {momento_en_palabras(r.fecha_hora)}"
        for r in reservas
    ]
    return (
        "Tiene estos turnos pendientes:\n" + "\n".join(lineas)
        + f"\n\n¿Cuál quiere {accion}? Puede indicarme el número o el trámite."
    )


def sin_turnos_pendientes(canal: Canal, cambiar: bool = False) -> str:
    if cambiar:
        return "No tiene turnos pendientes para cambiar. Si quiere, le reservo uno: ¿para qué trámite?"
    return "No tiene turnos pendientes para cancelar. ¿Lo ayudo con otra cosa?"


# Encabeza el ofrecimiento de horarios cuando el cambio no se pudo hacer: el
# código lo reconoce en el historial para entender una respuesta corta como
# "el de las 10:30".
MARCA_CAMBIO_NO_DISPONIBLE = "No pude cambiar su turno"


def cambio_no_disponible(reserva: Reserva, motivo: str, alternativas: list, canal: Canal) -> str:
    encabezado = f"{MARCA_CAMBIO_NO_DISPONIBLE} {reserva.caso.referencia}: {motivo}"
    if not alternativas:
        return f"{encabezado} No encontré horarios libres en esos días. ¿Quiere probar con otra fecha?"
    opciones = [momento_en_palabras(momento) for momento in alternativas]
    if canal == Canal.voz:
        lista = ", ".join(opciones[:-1]) + (" o " if len(opciones) > 1 else "") + opciones[-1]
        return f"{encabezado} Tengo libre el {lista}. ¿Cuál le queda mejor?"
    return (
        f"{encabezado} Los horarios libres más cercanos son:\n"
        + "\n".join(f"- {opcion}" for opcion in opciones)
        + "\n\n¿Cuál le queda mejor?"
    )


def pedido_de_nuevo_horario(reserva: Reserva, canal: Canal) -> str:
    return (
        f"¿Para qué día y a qué hora quiere cambiar su turno de {reserva.turno.nombre} "
        f"del {momento_en_palabras(reserva.fecha_hora)}? Los turnos son "
        f"{horario_de_atencion(reserva.turno)}."
    )


def turno_reprogramado(reserva: Reserva, anterior: datetime, canal: Canal) -> str:
    nuevo = momento_en_palabras(reserva.fecha_hora)
    if canal == Canal.voz:
        return (
            f"Listo, pasé su turno de {reserva.turno.nombre} al {nuevo}. "
            "El horario anterior quedó libre."
        )
    lineas = [
        f"Listo, cambié su turno de {reserva.turno.nombre}.",
        "",
        f"Antes: {momento_en_palabras(anterior)}",
        f"Ahora: {nuevo}",
    ]
    if reserva.turno.sede:
        lineas.append(f"Lugar: {reserva.turno.sede}")
    lineas += [f"Número de caso: {reserva.caso.referencia}", "", "El horario anterior quedó libre."]
    return "\n".join(lineas)


def recordatorio_de_turno(reserva: Reserva) -> str:
    """El recordatorio del día anterior. En una sola línea: si la ventana de 24 h
    de WhatsApp está cerrada, sale dentro de la plantilla de seguimiento, que no
    admite saltos de línea."""
    donde = f", en {reserva.turno.sede}" if reserva.turno.sede else ""
    dia = reserva.fecha_hora.astimezone(ZONA_HORARIA).date()
    cuando = "para mañana, " if dia == ahora_local().date() + timedelta(days=1) else "para el "
    return (
        f"Le recordamos su turno de {reserva.turno.nombre} {cuando}"
        f"{momento_en_palabras(reserva.fecha_hora)}{donde} (número de caso "
        f"{reserva.caso.referencia}). Si no puede ir, responda \"cancelar mi turno\" y el "
        "horario queda libre para otra persona."
    )


def pedido_de_dia_y_hora(
    agenda: Turno | None, canal: Canal, libres: list[datetime] | None = None
) -> str:
    """Cuando quiere un turno pero todavía no dijo para qué día.

    Con `libres`, se le ofrecen horarios concretos que hoy están libres en la
    agenda, en vez de mandarlo a adivinar uno que quizás ya está tomado. Elige
    uno o dice otro: en los dos casos la reserva pasa por `reservar`, que
    vuelve a controlar el cupo con la agenda bloqueada."""
    if agenda is None:
        return "¿Para qué trámite es el turno, y qué día y a qué hora le queda bien?"
    if libres:
        opciones = [momento_en_palabras(momento) for momento in libres]
        if canal == Canal.voz:
            # "a las 9" y no "a las 9:00": dicho en voz alta, el ":00" sobra.
            habladas = [opcion.removesuffix(":00") for opcion in opciones]
            lista = ", el ".join(habladas[:-1]) + (" o el " if len(habladas) > 1 else "") + habladas[-1]
            return (
                f"Para {agenda.nombre} tengo libre el {lista}. "
                "¿Le queda bien alguno? Si prefiere otro día, dígamelo."
            )
        return (
            f"Estos son los próximos horarios libres de {agenda.nombre}:\n"
            + "\n".join(f"- {opcion}" for opcion in opciones)
            + "\n\n¿Le queda bien alguno? Si prefiere otro día u horario, dígame cuál."
        )
    return (
        f"¿Qué día y a qué hora le queda bien? Los turnos de {agenda.nombre} son "
        f"{horario_de_atencion(agenda)}."
    )
