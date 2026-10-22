"""Mide el modelo servido por Ollama sobre el conjunto de prueba del fine-tuning.

El notebook de Colab midió el modelo con el prompt del entrenamiento, que pide un
único JSON con intención, confianza y llamada a herramienta. La aplicación no lo
usa así: clasifica en el intake con salida estructurada y ejecuta en el ejecutor
con las herramientas reales. Este script mide las dos cosas, para saber si lo
que se ganó con el ajuste se sostiene por el camino de producción.

Además de la comparación exacta del notebook, informa una comparación de los
parámetros estructurados: los campos de texto libre (`descripcion`,
`referencia`) no se comparan, porque una paráfrasis válida no es un error (ver
finetuning/DEVLOG.md, "Los 5 fallos de tool calling").

No toca la base de datos: las herramientas se construyen solo para pasarle sus
esquemas al modelo, nunca se ejecutan.

Uso:
    python -m scripts.evaluar_modelo_local                 # camino de la app
    python -m scripts.evaluar_modelo_local --modo entrenamiento
    python -m scripts.evaluar_modelo_local --detalle salida.jsonl
"""

import argparse
import asyncio
import json
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents import llm
from app.agents.ejecutor import construir_tools, prompt_del_sistema
from app.agents.intake import SYSTEM_INTAKE
from app.db.models import Canal
from app.schemas.agente import ClasificacionIntent

PRUEBA = Path(__file__).resolve().parent.parent / "finetuning/data/prueba_tool_calling.jsonl"
UMBRAL_CONFIANZA = 0.6
CAMPOS_LIBRES = {"descripcion", "referencia"}
# Las fechas esperadas del conjunto de prueba (noviembre y diciembre de 2026)
# se escribieron mirando desde esta fecha: "el jueves 5" es el 5 de noviembre.
HOY_DEL_DATASET = datetime(2026, 10, 19)

# Copia literal del SYSTEM_PROMPT del notebook (celda de armado del dataset).
SYSTEM_ENTRENAMIENTO = (
    'Sos el agente de atención ciudadana de un organismo público argentino.\n'
    'Para cada mensaje del ciudadano, devolvé un único objeto JSON con esta forma '
    'exacta, sin texto fuera del JSON:\n\n'
    '{"intencion": "consulta|reclamo|reserva|tramite|otro", "confianza": 0.0 a 1.0, '
    '"llamada_herramienta": null o {"nombre": '
    '"crear_reclamo|crear_reserva|consultar_estado_caso", "parametros": {...}}, '
    '"respuesta": "texto para el ciudadano"}\n\n'
    'Reglas:\n'
    '- Tratá al ciudadano de "usted", con lenguaje simple y claro, sin tecnicismos.\n'
    '- "llamada_herramienta" va en null si falta un dato necesario para ejecutar la '
    'acción; en ese caso "respuesta" repregunta justo lo que falta.\n'
    '- "tramite" nunca lleva llamada_herramienta: todavía no existe esa tool, '
    'siempre escala a un operador.\n'
    '- Nunca inventes un parámetro que el ciudadano no haya dicho.\n'
    '- "respuesta" en texto plano: sin markdown, sin asteriscos ni guiones de lista.'
)


def _parsear_json(texto: str) -> dict | None:
    try:
        return json.loads(texto.strip())
    except json.JSONDecodeError:
        coincidencia = re.search(r"\{.*\}", texto, re.DOTALL)
        if coincidencia:
            try:
                return json.loads(coincidencia.group(0))
            except json.JSONDecodeError:
                return None
        return None


def _estructurados(llamada: dict | None) -> tuple | None:
    """Herramienta + parámetros que no son texto libre, normalizados."""
    if not llamada:
        return None
    parametros = {
        clave: str(valor).strip().lower()
        for clave, valor in (llamada.get("parametros") or {}).items()
        if clave not in CAMPOS_LIBRES
    }
    return llamada.get("nombre"), tuple(sorted(parametros.items()))


async def _por_entrenamiento(instruccion: str) -> dict:
    modelo = llm.get_llm_ejecutor()
    respuesta = await modelo.ainvoke(
        [SystemMessage(content=SYSTEM_ENTRENAMIENTO), HumanMessage(content=instruccion)]
    )
    crudo = respuesta.content if isinstance(respuesta.content, str) else str(respuesta.content)
    pred = _parsear_json(crudo)
    if pred is None:
        return {"crudo": crudo, "error": "sin JSON válido"}
    return {
        "crudo": crudo,
        "intencion": pred.get("intencion"),
        "confianza": pred.get("confianza", 0),
        "llamada": pred.get("llamada_herramienta"),
    }


async def _por_la_app(instruccion: str) -> dict:
    clasificador = llm.get_llm_intake().with_structured_output(ClasificacionIntent)
    clasificacion: ClasificacionIntent = await clasificador.ainvoke(
        [
            SystemMessage(content=SYSTEM_INTAKE),
            HumanMessage(content=f"Mensaje del ciudadano (canal whatsapp): {instruccion}"),
        ]
    )

    # Ciudadano ya identificado: si no, el ejecutor (con razón) pide nombre y
    # DNI antes de cualquier gestión, y eso no es lo que mide este conjunto.
    estado = {
        "ciudadano_id": str(uuid.uuid4()),
        "canal": "whatsapp",
        "intencion": clasificacion.intencion,
        "identificado": True,
    }
    tools = construir_tools(None, estado)
    modelo = llm.get_llm_ejecutor().bind_tools(tools)
    respuesta = await modelo.ainvoke(
        [
            SystemMessage(content=prompt_del_sistema(Canal.whatsapp, hoy=HOY_DEL_DATASET)),
            HumanMessage(content=instruccion),
        ]
    )

    llamada = None
    derivada = False
    if respuesta.tool_calls:
        primera = respuesta.tool_calls[0]
        if primera["name"] == "derivar_a_operador":
            # Es lo que el entrenamiento expresa con llamada_herramienta=null en
            # un trámite: no hay tool, va a una persona.
            derivada = True
        else:
            llamada = {"nombre": primera["name"], "parametros": primera["args"]}
    return {
        "intencion": clasificacion.intencion,
        "confianza": clasificacion.confianza,
        "llamada": llamada,
        "derivada": derivada,
        "respuesta": respuesta.content if not respuesta.tool_calls else "",
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--modo", choices=["app", "entrenamiento"], default="app")
    parser.add_argument("--detalle", type=Path, help="Guardar el detalle por ejemplo (JSONL)")
    parser.add_argument("--limite", type=int, help="Evaluar solo los primeros N ejemplos")
    args = parser.parse_args()

    prueba = [json.loads(linea) for linea in PRUEBA.open(encoding="utf-8")]
    if args.limite:
        prueba = prueba[: args.limite]
    evaluar = _por_la_app if args.modo == "app" else _por_entrenamiento

    intencion_ok = falsos_positivos = tool_exacta = tool_estructurada = errores = 0
    detalle = []
    inicio = time.perf_counter()

    for numero, ejemplo in enumerate(prueba, start=1):
        try:
            pred = await evaluar(ejemplo["instruccion"])
        except Exception as error:  # una falla de un ejemplo no corta la corrida
            pred = {"error": f"{type(error).__name__}: {error}"}

        fila = {
            "instruccion": ejemplo["instruccion"],
            "intencion_esperada": ejemplo["intencion"],
            "llamada_esperada": ejemplo["llamada_herramienta"],
            **pred,
        }
        if "error" in pred:
            errores += 1
        else:
            acierto = pred["intencion"] == ejemplo["intencion"]
            intencion_ok += acierto
            if not acierto and (pred.get("confianza") or 0) >= UMBRAL_CONFIANZA:
                falsos_positivos += 1
            exacta = pred["llamada"] == ejemplo["llamada_herramienta"]
            estructurada = _estructurados(pred["llamada"]) == _estructurados(
                ejemplo["llamada_herramienta"]
            )
            tool_exacta += exacta
            tool_estructurada += estructurada
            fila.update(intencion_ok=acierto, tool_exacta=exacta, tool_estructurada=estructurada)
        detalle.append(fila)
        print(
            f"[{numero}/{len(prueba)}] "
            + ("ERROR " + pred["error"] if "error" in pred else
               f"intención {'ok' if fila['intencion_ok'] else 'MAL'}, "
               f"tool {'ok' if fila['tool_estructurada'] else 'MAL'}"),
            file=sys.stderr,
        )

    total = len(prueba)
    segundos = time.perf_counter() - inicio
    print(f"\nModo: {args.modo} - modelos: intake={llm.settings.agente_modelo_intake}, "
          f"ejecutor={llm.settings.agente_modelo_ejecutor}")
    print(f"Total evaluado: {total} ({segundos / max(total, 1):.1f} s por ejemplo)")
    print(f"Errores (sin respuesta usable): {errores}")
    print(f"Exactitud de intención: {intencion_ok / total:.1%} ({intencion_ok}/{total})")
    print(f"Falsos positivos (confianza >= {UMBRAL_CONFIANZA}, intención incorrecta): "
          f"{falsos_positivos}")
    print(f"Tool calling exacto (como el notebook): {tool_exacta / total:.1%} "
          f"({tool_exacta}/{total})")
    print(f"Tool calling sin campos de texto libre: {tool_estructurada / total:.1%} "
          f"({tool_estructurada}/{total})")

    if args.detalle:
        with args.detalle.open("w", encoding="utf-8") as archivo:
            for fila in detalle:
                archivo.write(json.dumps(fila, ensure_ascii=False) + "\n")
        print(f"Detalle en {args.detalle}")


if __name__ == "__main__":
    asyncio.run(main())
