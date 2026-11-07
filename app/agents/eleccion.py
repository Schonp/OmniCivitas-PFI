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


# --- Por voz -------------------------------------------------------------------

_NUMEROS_HABLADOS = {
    "1": 1, "uno": 1, "una": 1, "primero": 1, "primera": 1, "primer": 1,
    "2": 2, "dos": 2, "segundo": 2, "segunda": 2,
    "3": 3, "tres": 3, "tercero": 3, "tercera": 3, "tercer": 3,
}
# Lo que rodea al número cuando se elige hablando: "sí, el uno", "quiero seguir
# con el segundo", "el número dos, por favor".
_RELLENO_ELECCION = {
    "si", "sí", "el", "la", "los", "las", "de", "del", "con", "por", "favor", "eh", "bueno",
    "numero", "número", "nro", "opcion", "opción", "caso", "pedido", "quiero", "quisiera",
    "seguir", "sigo", "sigamos", "seguimos", "continuar", "continuo", "continúo", "retomar",
    "es", "ese", "esa",
    "mismo", "misma", "dale", "ok", "okay", "claro", "y", "a", "al", "lo", "me", "gustaria",
    "gustaría", "con", "que", "en", "curso",
}
# Con un solo caso ofrecido, "sí, sigamos con ese" alcanza para elegirlo.
_SIGUE_CON_ESE = {"si", "sí", "seguir", "sigo", "sigamos", "seguimos", "continuar", "continuo", "continúo",
                  "retomar", "ese", "esa", "mismo", "misma", "dale"}


def armar_ofertas_voz(casos_en_curso: list[Caso]) -> list[dict]:
    """Por voz se ofrecen solo los casos, numerados desde uno: el menú de tipos
    no se lee en una llamada."""
    return [{"numero": i, "caso_id": str(caso.id)} for i, caso in enumerate(casos_en_curso, start=1)]


def resolver_voz(mensaje: str, ofertas: list[dict]) -> dict | None:
    """La oferta que eligió el ciudadano hablando, o None si no eligió ninguna.

    Estricto como `resolver`: cuenta si lo que dijo es la elección y nada más.
    "Quiero reservar un turno" no elige nada aunque haya casos ofrecidos."""
    if not ofertas:
        return None
    palabras = [p for p in re.split(r"[^\wáéíóúñü]+", mensaje.lower()) if p]
    resto = [p for p in palabras if p not in _RELLENO_ELECCION]
    if len(resto) == 1 and resto[0] in _NUMEROS_HABLADOS:
        elegido = _NUMEROS_HABLADOS[resto[0]]
        return next((o for o in ofertas if o["numero"] == elegido), None)
    if not resto and len(ofertas) == 1 and any(p in _SIGUE_CON_ESE for p in palabras):
        return ofertas[0]
    return None


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
