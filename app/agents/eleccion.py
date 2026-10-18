"""Las opciones numeradas que se le ofrecen al ciudadano, y cómo se resuelven.

El saludo enumera qué puede hacer —reclamo, consulta, trámite— y, debajo, los
casos que tiene en curso. La numeración es corrida (los casos siguen en 4) para
que haya una sola lista: con dos listas que arrancan en 1, un "2" es ambiguo.

La respuesta se resuelve **por código, no con el LLM**. Un "4" pelado no tiene
nada que clasificar: sin el menú delante, el modelo no puede saber qué eligió el
ciudadano, y de hecho el menú no queda en el historial porque un saludo no abre
caso. Acá se guarda qué se ofreció —viaja en el checkpointer del hilo— y se
mapea el número. De paso no gasta tokens y no se equivoca.
"""

import re
import uuid

from app.db.models import Caso

# Estricto a propósito. "Necesito un turno el 4 de octubre" también tiene un
# número, y no es una elección: solo cuenta si el mensaje entero es el número,
# con a lo sumo una muletilla adelante.
_ELECCION = re.compile(
    r"^(?:la |el |los |opcion |opción |opcion nro |numero |número |nro |n° |caso )?"
    r"#?(\d{1,2})[.)]?$",
    re.IGNORECASE,
)

TIPOS_DEL_MENU = ("reclamo", "consulta", "tramite")

ETIQUETA_TIPO = {"reclamo": "Reclamo", "consulta": "Consulta", "tramite": "Trámite"}


def armar_ofertas(casos_en_curso: list[Caso]) -> list[dict]:
    """Qué significa cada número, en el mismo orden en que se muestra."""
    ofertas: list[dict] = [
        {"numero": indice, "intencion": tipo}
        for indice, tipo in enumerate(TIPOS_DEL_MENU, start=1)
    ]
    siguiente = len(TIPOS_DEL_MENU) + 1
    for desplazamiento, caso in enumerate(casos_en_curso):
        ofertas.append({"numero": siguiente + desplazamiento, "caso_id": str(caso.id)})
    return ofertas


def numero_de_caso(ofertas: list[dict], caso_id: uuid.UUID) -> int | None:
    for oferta in ofertas:
        if oferta.get("caso_id") == str(caso_id):
            return oferta["numero"]
    return None


def es_eleccion(mensaje: str) -> bool:
    return _ELECCION.match(mensaje.strip()) is not None


def resolver(mensaje: str, ofertas: list[dict]) -> dict | None:
    """La oferta que eligió el ciudadano, o None si el mensaje no es un número."""
    if not ofertas:
        return None
    coincidencia = _ELECCION.match(mensaje.strip())
    if coincidencia is None:
        return None
    elegido = int(coincidencia.group(1))
    for oferta in ofertas:
        if oferta["numero"] == elegido:
            return oferta
    return None
