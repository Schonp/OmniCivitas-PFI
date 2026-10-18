"""Descarga MULTI3NLU++ (español) y lo reetiqueta a las 5 categorías del
Proyecto.

El dataset está publicado como `uoe-nlp/multi3-nlu` en Hugging Face, no como
dataset cargable con `datasets.load_dataset` (son archivos JSON sueltos por
idioma/dominio/fold). Se descargan los archivos con `huggingface_hub` y se
unen: los "folds" (20 por dominio) resultaron ser una partición simple y
disjunta del dataset completo, no splits de evaluación con los que haya que
quedarse por separado — ver DEVLOG.md ("Los folds de MULTI3NLU++ no son lo
que parecen").

Igual que en `preparar_massive.py`, las filas resultantes solo entrenan
intención + confianza (`llamada_herramienta` y `respuesta` quedan en None):
el contenido es de dominios bancario/hotelero, no de atención ciudadana.

Uso: .venv/Scripts/python.exe preparar_multi3nlu.py
Salida: data/multi3nlu_relabeled.jsonl
"""
import collections
import json
from pathlib import Path

from huggingface_hub import hf_hub_download

from esquema import EjemploEntrenamiento
from mapeo_multi3nlu import EXCLUSIONES_REVISADAS_A_MANO, clasificar

REPO = "uoe-nlp/multi3-nlu"
DOMINIOS = ["banking", "hotels"]
N_FOLDS = 20
SALIDA = Path(__file__).parent / "data" / "multi3nlu_relabeled.jsonl"


def descargar_dominio(dominio: str) -> list[dict]:
    filas = []
    for i in range(N_FOLDS):
        ruta = hf_hub_download(REPO, f"spanish/{dominio}/fold{i}.json", repo_type="dataset")
        filas.extend(json.load(open(ruta, encoding="utf-8")))
    return filas


def main() -> None:
    conteo_categoria: collections.Counter = collections.Counter()
    sin_intents = 0
    excluidas_revision = 0
    ejemplos: list[EjemploEntrenamiento] = []

    for dominio in DOMINIOS:
        filas = descargar_dominio(dominio)
        print(f"{dominio}: {len(filas)} filas descargadas")
        for fila in filas:
            if fila.get("text") in EXCLUSIONES_REVISADAS_A_MANO:
                excluidas_revision += 1
                continue
            tags = fila.get("intents")
            if not tags:
                # Turno sin intención propia (solo completa un slot de una
                # pregunta anterior) — no hay nada que clasificar sin el
                # contexto de la conversación completa. Ver DEVLOG.md.
                sin_intents += 1
                continue
            resultado = clasificar(set(tags))
            if resultado is None:
                continue
            categoria, confianza = resultado
            ejemplos.append(
                EjemploEntrenamiento(
                    instruccion=fila["text"],
                    intencion=categoria,
                    confianza=confianza,
                    llamada_herramienta=None,
                    respuesta=None,
                    fuente="multi3nlu",
                )
            )
            conteo_categoria[categoria] += 1

    SALIDA.parent.mkdir(exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        for ejemplo in ejemplos:
            f.write(ejemplo.model_dump_json() + "\n")

    print()
    print(f"Excluidas por revisión manual (niegan el problema o son corrección de datos): {excluidas_revision}")
    print(f"Descartadas (sin campo 'intents', solo slots): {sin_intents}")
    print(f"Ejemplos escritos: {len(ejemplos)} -> {SALIDA}")
    print("Distribución por categoría:")
    for categoria, cantidad in sorted(conteo_categoria.items()):
        porcentaje = 100 * cantidad / len(ejemplos)
        print(f"  {categoria:10s} {cantidad:6d}  ({porcentaje:4.1f}%)")


if __name__ == "__main__":
    main()
