"""Confirmación al ciudadano de una gestión que ya se ejecutó.

Cuando `crear_reclamo` o `crear_reserva` salen bien, el mensaje de cierre se
arma acá con los datos que devolvió la herramienta, en vez de pedírselo al
modelo en una segunda vuelta. El modelo local se ajustó con ejemplos de un solo
turno y nunca vio el resultado de una herramienta: en esa segunda vuelta
completaba con cosas que no pasaron ("ya quedó derivado", "le van a pedir el
comprobante"). Una confirmación con datos reales no puede inventar nada, y en
una llamada ahorra una inferencia entera antes de que el ciudadano escuche algo.
"""

from datetime import datetime

from app.db.models import Canal
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
        return (
            f"Listo, registré su reclamo{sobre}, con el número de caso {referencia}. "
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
    if voz:
        cuando = f" para el {fecha[0]} a {_hora_hablada(fecha[1])}" if fecha else ""
        return f"Listo, le reservé el turno de {turno}{cuando}. El número de caso es {referencia}."
    lineas = [f"Le reservé el turno de {turno}.", "", f"Turno: {turno}"]
    if fecha:
        lineas.append(f"Día y hora: {fecha[0]}, {fecha[1]} h")
    lineas.append(f"Número de caso: {referencia}")
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


def agradecimiento(salida_identidad: dict) -> str:
    """Prefijo cuando el ciudadano se identificó en el mismo mensaje."""
    nombre = (salida_identidad.get("nombre") or "").split()
    return f"Gracias, {nombre[0].capitalize()}. " if nombre else "Gracias. "
