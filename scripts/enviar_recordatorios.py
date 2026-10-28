"""Manda el recordatorio de los turnos de mañana.

Uso:  python -m scripts.enviar_recordatorios [AAAA-MM-DD]

Pensado para correr una vez por día (Programador de tareas de Windows o cron),
por ejemplo a las 10, cuando ya no quedan dudas de qué turnos tiene el día
siguiente. Correrlo dos veces no duplica nada: solo manda los que faltan.
"""

import asyncio
import sys
from datetime import date

from app.channels.recordatorios import enviar_recordatorios
from app.db.session import async_session_factory


async def main() -> None:
    dia = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None
    async with async_session_factory() as db:
        resumen = await enviar_recordatorios(db, dia)
    print(f"Turnos del {resumen['dia']}: {resumen['enviados']} recordatorios enviados de {resumen['total']}.")
    for falla in resumen["no_enviados"]:
        print(f"  - {falla['referencia']}: no salió ({falla['motivo']})")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
