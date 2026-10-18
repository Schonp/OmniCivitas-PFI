"""Candado de instancia única, para que un poller no corra por duplicado.

El canal de correo funciona por polling: `_leer_no_leidos` busca los mensajes
sin leer, los baja y recién ahí los marca como leídos. Con dos procesos sobre
el mismo buzón esa ventana alcanza para que los dos se traigan el mismo correo,
así que el mensaje del ciudadano se procesa dos veces y le llegan dos
respuestas del agente. Pasó de verdad, con dos pollers arrancados con dos
minutos de diferencia desde terminales distintas.

Se usa el bloqueo de archivos del sistema operativo (`msvcrt` en Windows,
`fcntl` en Linux) y no un archivo con el PID adentro: el sistema suelta el
candado cuando el proceso muere, incluso si lo mataron a la fuerza. Con un
archivo centinela habría que distinguir un candado vivo de uno que quedó
huérfano, y averiguar si un PID sigue vivo no es portable (en Windows
`os.kill(pid, 0)` no consulta: termina el proceso).

**Alcance:** el candado es por máquina, no distribuido. Dos contenedores con
sistemas de archivos separados no se ven entre sí. Para eso haría falta un
candado en Redis, que este prototipo no necesita: el poller corre en una sola
máquina.
"""

import sys
import tempfile
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class InstanciaEnUso(RuntimeError):
    """Ya hay otro proceso con el candado tomado."""


def ruta_de_candado(nombre: str) -> Path:
    """En el directorio temporal del sistema: no ensucia el repo y en el
    contenedor existe siempre, sin depender de permisos de escritura."""
    return Path(tempfile.gettempdir()) / f"omnicivitas-{nombre}.lock"


def _tomar(descriptor: int) -> None:
    if sys.platform == "win32":
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _soltar(descriptor: int) -> None:
    if sys.platform == "win32":
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def instancia_unica(nombre: str) -> Iterator[Path]:
    """Toma el candado `nombre` o levanta `InstanciaEnUso` si ya está tomado."""
    ruta = ruta_de_candado(nombre)
    archivo = ruta.open("a+")
    try:
        archivo.seek(0)
        try:
            # Windows bloquea a partir de la posición actual, por eso el seek.
            _tomar(archivo.fileno())
        except OSError as error:
            raise InstanciaEnUso(
                f"Ya hay otro proceso corriendo con el candado '{nombre}' ({ruta})"
            ) from error

        try:
            yield ruta
        finally:
            archivo.seek(0)
            _soltar(archivo.fileno())
    finally:
        archivo.close()
