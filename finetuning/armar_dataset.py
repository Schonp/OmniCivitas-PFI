"""Combina las fuentes y arma los splits finales de entrenamiento.

Reglas de split (documentadas en DEVLOG.md, "Cómo se separan los splits"):

- Los ejemplos SIN llamada_herramienta (todo MASSIVE + los manuales que no
  llaman tool) entran a un pool general, dividido 90/10 estratificado por
  `intencion` en train/validación. Nunca van al conjunto de prueba: ese
  conjunto es sólo de tool calling, como pide la tesis.
- Los ejemplos CON llamada_herramienta (hoy sólo del set manual) se separan
  aparte y se dividen train/validación/prueba estratificado por el nombre de
  la herramienta, para que el conjunto de prueba quede compuesto
  exclusivamente por tool calling y sea disjunto del entrenamiento.

Uso: .venv/Scripts/python.exe armar_dataset.py
Salida: data/train.jsonl, data/validacion.jsonl, data/prueba_tool_calling.jsonl
"""
import json
from pathlib import Path

from sklearn.model_selection import train_test_split

from esquema import EjemploEntrenamiento

DATA = Path(__file__).parent / "data"
SEMILLA = 42


def leer_jsonl(ruta: Path) -> list[EjemploEntrenamiento]:
    return [
        EjemploEntrenamiento.model_validate_json(linea)
        for linea in open(ruta, encoding="utf-8")
        if linea.strip()
    ]


def escribir_jsonl(ruta: Path, ejemplos: list[EjemploEntrenamiento]) -> None:
    with open(ruta, "w", encoding="utf-8") as f:
        for e in ejemplos:
            f.write(e.model_dump_json() + "\n")


def split_estratificado(
    ejemplos: list[EjemploEntrenamiento], etiquetas: list[str], proporciones: list[float]
) -> list[list[EjemploEntrenamiento]]:
    """Divide `ejemplos` según `proporciones` (suman 1), estratificado por
    `etiquetas`. Si una clase tiene muy pocos ejemplos para estratificar con
    ese número de cortes, cae a split aleatorio simple (ver DEVLOG.md)."""
    assert abs(sum(proporciones) - 1.0) < 1e-6
    try:
        restantes, etiquetas_restantes = ejemplos, etiquetas
        partes: list[list[EjemploEntrenamiento]] = []
        acumulado = 0.0
        for proporcion in proporciones[:-1]:
            frac = proporcion / (1 - acumulado)
            parte, restantes, _, etiquetas_restantes = train_test_split(
                restantes,
                etiquetas_restantes,
                train_size=frac,
                random_state=SEMILLA,
                stratify=etiquetas_restantes,
            )
            partes.append(parte)
            acumulado += proporcion
        partes.append(restantes)
        return partes
    except ValueError as error:
        print(f"  [!] No se pudo estratificar ({error}); split aleatorio simple.")
        restantes = list(ejemplos)
        partes = []
        acumulado = 0.0
        for proporcion in proporciones[:-1]:
            frac = proporcion / (1 - acumulado)
            parte, restantes = train_test_split(restantes, train_size=frac, random_state=SEMILLA)
            partes.append(parte)
            acumulado += proporcion
        partes.append(restantes)
        return partes


def main() -> None:
    masivos = leer_jsonl(DATA / "massive_relabeled.jsonl")
    multi3nlu = leer_jsonl(DATA / "multi3nlu_relabeled.jsonl")
    manuales = leer_jsonl(Path(__file__).parent / "ejemplos_tool_calling.jsonl")
    generados = leer_jsonl(Path(__file__).parent / "ejemplos_generados.jsonl")
    manuales = manuales + generados

    sin_tool = masivos + multi3nlu + [e for e in manuales if e.llamada_herramienta is None]
    con_tool = [e for e in manuales if e.llamada_herramienta is not None]

    print(f"Pool general (sin tool calling): {len(sin_tool)}")
    print(f"Pool de tool calling: {len(con_tool)}")

    train_general, val_general = split_estratificado(
        sin_tool, [e.intencion for e in sin_tool], [0.9, 0.1]
    )

    train_tool, val_tool, test_tool = split_estratificado(
        con_tool, [e.llamada_herramienta.nombre for e in con_tool], [0.6, 0.2, 0.2]
    )

    train = train_general + train_tool
    validacion = val_general + val_tool
    prueba = test_tool

    escribir_jsonl(DATA / "train.jsonl", train)
    escribir_jsonl(DATA / "validacion.jsonl", validacion)
    escribir_jsonl(DATA / "prueba_tool_calling.jsonl", prueba)

    print()
    print(f"train.jsonl:               {len(train)} ({len(train_general)} generales + {len(train_tool)} tool calling)")
    print(f"validacion.jsonl:          {len(validacion)} ({len(val_general)} generales + {len(val_tool)} tool calling)")
    print(f"prueba_tool_calling.jsonl: {len(prueba)} (sólo tool calling, disjunto de train/validación)")


if __name__ == "__main__":
    main()
