"""Descarga MASSIVE (es) y lo reetiqueta a las 5 categorías del Proyecto.

El dataset original (AmazonScience/massive) usa un loading script que las
versiones recientes de `datasets` ya no soportan (ver DEVLOG.md, "Mirror de
MASSIVE"). Se usa en cambio el mirror en Parquet `mteb/amazon_massive_intent`,
que trae las mismas 60 intenciones y el mismo texto en español.

Las filas resultantes solo entrenan intención + confianza: `llamada_herramienta`
y `respuesta` quedan en None a propósito (ver DEVLOG.md, "Qué sí y qué no
enseña MASSIVE"), porque el contenido es de un asistente genérico (alarmas,
IoT, música) y no de atención ciudadana — inventarle una respuesta de
organismo público a "despertame a las nueve" sería un dato falso.

Uso: .venv/Scripts/python.exe preparar_massive.py
Salida: data/massive_relabeled.jsonl
"""
import collections
import json
from pathlib import Path

from datasets import load_dataset

from esquema import EjemploEntrenamiento
from mapeo_massive import MAPEO

SALIDA = Path(__file__).parent / "data" / "massive_relabeled.jsonl"


def main() -> None:
    ds = load_dataset("mteb/amazon_massive_intent", "es", split="train")

    conteo_categoria: collections.Counter = collections.Counter()
    descartadas = 0
    ejemplos: list[EjemploEntrenamiento] = []

    for fila in ds:
        intencion_massive = fila["label_text"]
        mapeo = MAPEO.get(intencion_massive)
        if mapeo is None:
            descartadas += 1
            continue
        categoria, confianza = mapeo
        ejemplos.append(
            EjemploEntrenamiento(
                instruccion=fila["text"],
                intencion=categoria,
                confianza=confianza,
                llamada_herramienta=None,
                respuesta=None,
                fuente="massive",
            )
        )
        conteo_categoria[categoria] += 1

    SALIDA.parent.mkdir(exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        for ejemplo in ejemplos:
            f.write(ejemplo.model_dump_json() + "\n")

    print(f"Filas de MASSIVE procesadas: {len(ds)}")
    print(f"Descartadas (sin mapeo): {descartadas}")
    print(f"Ejemplos escritos: {len(ejemplos)} -> {SALIDA}")
    print("Distribución por categoría:")
    for categoria, cantidad in sorted(conteo_categoria.items()):
        porcentaje = 100 * cantidad / len(ejemplos)
        print(f"  {categoria:10s} {cantidad:6d}  ({porcentaje:4.1f}%)")


if __name__ == "__main__":
    main()
