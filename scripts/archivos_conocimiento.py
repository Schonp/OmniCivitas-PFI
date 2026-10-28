"""Lectura de los documentos de ejemplo de la carpeta `conocimiento/`.

Aparte del script de carga a propósito: este módulo no toca la base de datos,
así que lo puede importar el armado del dataset de fine-tuning en Colab, donde
no hay `.env` ni base.
"""

from pathlib import Path

CARPETA_CONOCIMIENTO = Path(__file__).resolve().parent.parent / "conocimiento"


def leer_carpeta(carpeta: Path) -> list[tuple[str, str, str]]:
    """(título, contenido, nombre de archivo) de cada .txt de la carpeta. El
    título es la primera línea y el contenido, el resto."""
    documentos = []
    for archivo in sorted(carpeta.glob("*.txt")):
        titulo, _, contenido = archivo.read_text(encoding="utf-8").partition("\n")
        documentos.append((titulo.strip(), contenido.strip(), archivo.name))
    return documentos
