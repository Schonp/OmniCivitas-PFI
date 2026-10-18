# Fine-tuning del LLM local (Qwen2.5-3B-Instruct)

Pipeline de datos para el fine-tuning descripto en la tesis (`chapter04.tex`,
"Entrenamiento del modelo de lenguaje"). Entorno separado del resto del
proyecto — no es parte de la app que corre en producción, es tooling de
preparación de dataset. Corre en local, sin GPU; el entrenamiento QLoRA en sí
va en Colab (fuera de este repo, ver DEVLOG.md).

Para el relato de decisiones, hallazgos y lo que falta, ver **DEVLOG.md** —
es el documento pensado para integrarse a la tesis.

## Setup

```bash
cd finetuning
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

## Uso

```bash
.venv/Scripts/python.exe preparar_massive.py     # descarga y reetiqueta MASSIVE (es)
.venv/Scripts/python.exe preparar_multi3nlu.py   # descarga y reetiqueta MULTI3NLU++ (es)
.venv/Scripts/python.exe generar_ejemplos.py     # genera ejemplos de tool calling por plantilla
.venv/Scripts/python.exe armar_dataset.py        # combina todo y arma los splits finales
```

Salida en `data/` (gitignorado, se regenera con los scripts):
- `massive_relabeled.jsonl`
- `multi3nlu_relabeled.jsonl`
- `train.jsonl`
- `validacion.jsonl`
- `prueba_tool_calling.jsonl`

Versionados en la raíz de esta carpeta (no en `data/`), porque son el
contenido que de verdad enseña el dominio y tool calling — ninguna fuente
pública los puede reemplazar:
- `ejemplos_tool_calling.jsonl`: 47 ejemplos escritos y revisados uno por
  uno a mano.
- `ejemplos_generados.jsonl`: ~220 más, generados combinando plantillas con
  bancos de variación (calles, barrios, fechas) — ver DEVLOG.md ("Ejemplos
  generados por plantilla") antes de confiar en ellos sin revisión.
