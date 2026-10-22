# Modelo local con Ollama

El grafo de agentes no usa ninguna API comercial: todas las llamadas al modelo
(intake, ejecutor, resumen, mensajes de escalado, agrupador de reclamos) van a
Ollama corriendo en la misma máquina (ver `app/agents/llm.py`).

## Puesta en marcha

1. Instalar Ollama (Windows):

   ```
   winget install Ollama.Ollama
   ```

   Queda corriendo como servicio en `http://localhost:11434`.

2. Descargar el modelo exportado por el notebook desde Google Drive
   (`omnicivitas-finetune/qwen_omnicivitas_gguf_gguf/Qwen2.5-3B-Instruct.Q4_K_M.gguf`,
   unos 1,9 GB) y dejarlo en esta carpeta (`ollama/`). Está en `.gitignore`.

3. Darlo de alta en Ollama, desde la raíz del repo:

   ```
   ollama create omnicivitas-qwen -f ollama/Modelfile
   ```

4. Probar que responde:

   ```
   ollama run omnicivitas-qwen "Hay un poste de luz quemado en Rivadavia 1200"
   ```

El nombre `omnicivitas-qwen` es el que espera la configuración
(`AGENTE_MODELO_INTAKE` y `AGENTE_MODELO_EJECUTOR`).

## Medir el modelo servido

`scripts/evaluar_modelo_local.py` corre el conjunto de prueba del fine-tuning
(`finetuning/data/prueba_tool_calling.jsonl`) contra Ollama de dos maneras:

- `--modo entrenamiento`: con el prompt exacto del entrenamiento. Sirve para
  confirmar que el GGUF servido rinde lo mismo que lo medido en Colab.
- `--modo app` (por defecto): por el mismo camino que usa la aplicación (prompt
  del intake con salida estructurada, y prompt del ejecutor con las
  herramientas reales). Es el número que importa en producción.

```
python -m scripts.evaluar_modelo_local --modo entrenamiento
python -m scripts.evaluar_modelo_local
```
