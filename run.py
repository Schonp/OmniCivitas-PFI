"""Arranca la API en Windows con el event loop correcto.

`python -m uvicorn app.main:app` no sirve en Windows: uvicorn arma su loop
con la policy por defecto (ProactorEventLoop) antes de importar `app.main`,
así que fijar la policy adentro de ese módulo llega tarde -- psycopg (el
checkpointer de LangGraph) nunca conecta y cualquier mensaje que llegue al
grafo falla con "El checkpointer no está inicializado". Hay que fijar la
policy en este proceso ANTES de llamar a uvicorn.run(), no adentro de la app.

Deja de servir en uvicorn>=0.36 (empezó a ignorar la policy puesta antes de
run()) -- hoy el proyecto fija uvicorn==0.34.0, donde todavía funciona.

Uso: .venv/Scripts/python.exe run.py
(En Linux/Mac no hace falta nada de esto: `uvicorn app.main:app --reload`
anda directo, ProactorEventLoop es exclusivo de Windows.)
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
