import uuid

from sqlalchemy import Integer, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentoConocimiento

# Tamaño del fragmento que entra al contexto del LLM por documento.
MAX_CARACTERES_FRAGMENTO = 1500
MAX_DOCUMENTOS_CONTEXTO = 3
MIN_LARGO_PALABRA = 4

# Una coincidencia en el título dice mucho más que una en el cuerpo: el título
# es el tema del documento, el cuerpo puede nombrar algo al pasar.
PESO_TITULO = 2
PESO_CONTENIDO = 1

# Palabras que aparecen en casi cualquier mensaje y no aportan tema. Sin este
# filtro, un documento que contenga "para" se recupera ante cualquier consulta y
# desplaza al que de verdad responde, porque solo entran MAX_DOCUMENTOS_CONTEXTO.
# Solo palabras vacías: "turno", "reclamo" o "consulta" sí son señal.
PALABRAS_VACIAS = frozenset({
    "para", "pero", "porque", "como", "cuando", "donde", "cual", "cuales",
    "esta", "este", "esto", "esos", "esas", "eso", "aqui", "alli", "ahi",
    "tiene", "tengo", "tienen", "tener", "hace", "hacer", "hago",
    "quiero", "queria", "quisiera", "necesito", "necesita", "necesitaria",
    "puede", "puedo", "podria", "debe", "debo", "deberia",
    "hola", "buenas", "buenos", "gracias", "favor", "saludos", "estimados",
    "saber", "decir", "dice", "digo", "algo", "alguna", "alguno", "nada",
    "todo", "toda", "todos", "todas", "otra", "otro", "otros", "otras",
    "muy", "mas", "menos", "sobre", "desde", "hasta", "entre", "tambien",
    "seria", "estoy", "estan", "somos", "soy", "hubo", "habia",
    "usted", "ustedes", "mismo", "misma", "cosa", "cosas", "vez", "veces",
    "dias", "dia", "ayer", "hoy", "manana", "ahora", "aun", "solo",
})

# Vocales acentuadas y su equivalente plano. La gente escribe "arbol" o
# "publico" sin tilde, y el ILIKE no las une; se normalizan los dos lados.
_ACENTOS = "áéíóúüñÁÉÍÓÚÜÑ"
_SIN_ACENTOS = "aeiouunAEIOUUN"

_SIGNOS = ".,;:¿?¡!()\"'«»…"


def _sin_acentos(texto: str) -> str:
    return texto.translate(str.maketrans(_ACENTOS, _SIN_ACENTOS))


def _columna_normalizada(columna):
    """Misma normalización que `_sin_acentos`, pero del lado de Postgres.

    Se hace con `translate` y no con la extensión `unaccent` para no depender de
    un CREATE EXTENSION en la base.
    """
    return func.translate(func.lower(columna), _ACENTOS, _SIN_ACENTOS)


def palabras_significativas(mensaje: str) -> set[str]:
    """Palabras del mensaje que sirven para buscar: sin signos, sin acentos, de
    largo suficiente y que no sean muletillas."""
    palabras = set()
    for palabra in mensaje.split():
        limpia = _sin_acentos(palabra.strip(_SIGNOS).lower())
        if len(limpia) >= MIN_LARGO_PALABRA and limpia not in PALABRAS_VACIAS:
            palabras.add(limpia)
    return palabras


async def listar_documentos(db: AsyncSession) -> list[DocumentoConocimiento]:
    consulta = select(DocumentoConocimiento).order_by(DocumentoConocimiento.created_at.desc())
    return list((await db.execute(consulta)).scalars().all())


async def crear_documento(
    db: AsyncSession, *, titulo: str, contenido: str, nombre_archivo: str | None = None
) -> DocumentoConocimiento:
    documento = DocumentoConocimiento(
        titulo=titulo, contenido=contenido, nombre_archivo=nombre_archivo
    )
    db.add(documento)
    await db.commit()
    await db.refresh(documento)
    return documento


async def borrar_documento(db: AsyncSession, documento_id: uuid.UUID) -> bool:
    documento = await db.get(DocumentoConocimiento, documento_id)
    if documento is None:
        return False
    await db.delete(documento)
    await db.commit()
    return True


async def buscar_documentos_relevantes(db: AsyncSession, mensaje: str) -> list[str]:
    """Recuperación léxica con puntaje: documentos ordenados por cuántas palabras
    del mensaje mencionan, no por fecha de carga.

    Ordenar por fecha hacía que el documento correcto quedara afuera apenas la
    base crecía: como solo entran MAX_DOCUMENTOS_CONTEXTO, un documento nuevo que
    compartiera una palabra suelta desplazaba al que respondía la consulta.

    La búsqueda semántica con pgvector queda para la fase de RAG; la interfaz
    (mensaje → fragmentos) no cambia.
    """
    palabras = palabras_significativas(mensaje)
    if not palabras:
        return []

    titulo = _columna_normalizada(DocumentoConocimiento.titulo)
    contenido = _columna_normalizada(DocumentoConocimiento.contenido)

    puntaje = literal(0, Integer)
    for palabra in palabras:
        patron = f"%{palabra}%"
        puntaje = puntaje + case((titulo.like(patron), PESO_TITULO), else_=0)
        puntaje = puntaje + case((contenido.like(patron), PESO_CONTENIDO), else_=0)

    consulta = (
        select(DocumentoConocimiento)
        .where(puntaje > 0)
        # A igual puntaje gana el más reciente: si el organismo recargó un tema,
        # la versión nueva es la que vale.
        .order_by(puntaje.desc(), DocumentoConocimiento.created_at.desc())
        .limit(MAX_DOCUMENTOS_CONTEXTO)
    )
    documentos = (await db.execute(consulta)).scalars().all()
    return [
        f"{documento.titulo}: {documento.contenido[:MAX_CARACTERES_FRAGMENTO]}"
        for documento in documentos
    ]
