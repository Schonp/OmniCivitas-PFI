"""Carga la base de conocimiento del organismo con temas de atención al vecino.

Uso:  python -m scripts.seed_conocimiento

Es idempotente: saltea los títulos que ya están cargados, así que se puede
correr de nuevo sin duplicar.

Además de los documentos de abajo, carga los archivos de texto de la carpeta
`conocimiento/` del repositorio: los de `pautas_generales/` como pautas que el
agente aplica en todas las conversaciones, y los de `documentos/` como
información que se recupera por relevancia. Cada archivo lleva el título en la
primera línea y el contenido a partir de la tercera. Son texto plano a
propósito: es lo que más barato le sale leer al modelo, sin marcado que gaste
tokens.

Cómo está redactado el contenido, y por qué
-------------------------------------------
La recuperación es léxica (`buscar_documentos_relevantes`): parte el mensaje del
ciudadano en palabras de 4 letras o más y trae los documentos cuyo título o
contenido contengan **alguna** de ellas. Eso impone dos reglas de redacción:

1. **Cada documento nombra los sinónimos que usa la gente.** Nadie escribe
   "deterioro de la calzada": escribe "pozo", "bache" o "hueco". Si la palabra
   no está en el texto, el documento no se recupera.
2. **Se evitan las palabras comodín.** Las muletillas se filtran antes de
   buscar (`PALABRAS_VACIAS`), pero una palabra genérica que pase el filtro
   suma puntaje en cualquier mensaje y le puede quitar el lugar a un documento
   que sí servía, porque solo entran `MAX_DOCUMENTOS_CONTEXTO`.
"""

import asyncio

from sqlalchemy import select

from app.db.models import DocumentoConocimiento
from app.db.session import async_session_factory
from scripts.archivos_conocimiento import CARPETA_CONOCIMIENTO, leer_carpeta
from scripts.documentos_de_ejemplo import DOCUMENTOS


async def cargar() -> None:
    async with async_session_factory() as db:
        existentes = set(
            (await db.execute(select(DocumentoConocimiento.titulo))).scalars().all()
        )
        candidatos = [
            DocumentoConocimiento(titulo=titulo, contenido=contenido)
            for titulo, contenido in DOCUMENTOS
        ]
        for subcarpeta, general in (("pautas_generales", True), ("documentos", False)):
            candidatos += [
                DocumentoConocimiento(
                    titulo=titulo, contenido=contenido, nombre_archivo=archivo, general=general
                )
                for titulo, contenido, archivo in leer_carpeta(CARPETA_CONOCIMIENTO / subcarpeta)
            ]
        nuevos = [doc for doc in candidatos if doc.titulo not in existentes]
        if not nuevos:
            print("La base de conocimiento ya estaba al día: no se agregó nada.")
            return

        db.add_all(nuevos)
        await db.commit()

    print(f"Documentos cargados: {len(nuevos)}")
    for documento in nuevos:
        print(f"  - {documento.titulo}")
    salteados = len(candidatos) - len(nuevos)
    if salteados:
        print(f"Ya estaban cargados: {salteados}")


if __name__ == "__main__":
    asyncio.run(cargar())
