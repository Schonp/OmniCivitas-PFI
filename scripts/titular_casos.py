"""Pone título a los casos que no tienen, con la misma regla que usa el agente.

Los casos creados antes de que existiera el título (los de seed_demo, por
ejemplo) quedaban "Sin título" en el panel y el saludo de la llamada los
nombraba con las primeras palabras del vecino cortadas. Es idempotente: solo
toca los casos sin título, así que nunca pisa uno que puso el supervisor.

Uso:  python -m scripts.titular_casos            (muestra qué haría)
      python -m scripts.titular_casos --aplicar  (lo guarda)
"""

import asyncio
import sys

from sqlalchemy import select

from app.agents.titulos import titulo_automatico
from app.db.crud.interacciones import primeros_mensajes_de_casos
from app.db.models import Caso, Reserva, TipoCaso, Turno
from app.db.session import async_session_factory
from app.tools.reclamos import titulo_de_reclamo


async def titular(aplicar: bool) -> None:
    async with async_session_factory() as db:
        casos = list((await db.execute(select(Caso).where(Caso.titulo.is_(None)))).scalars().all())
        primeros = await primeros_mensajes_de_casos(db, [caso.id for caso in casos])
        agendas = dict(
            (
                await db.execute(
                    select(Reserva.caso_id, Turno.nombre).join(Turno, Turno.id == Reserva.turno_id)
                )
            ).all()
        )

        cambios = 0
        for caso in casos:
            if caso.tipo == TipoCaso.reclamo and caso.asunto:
                titulo = titulo_de_reclamo(caso.asunto)
            elif caso.tipo == TipoCaso.reserva and caso.id in agendas:
                titulo = agendas[caso.id][:120]
            else:
                titulo = titulo_automatico(caso.tipo, caso.asunto or primeros.get(caso.id))
            if titulo is None:
                continue
            print(f"  {caso.referencia}: {titulo}")
            caso.titulo = titulo
            cambios += 1

        if not aplicar:
            print(f"\nSimulacro: {cambios} casos tendrían título. Repetí con --aplicar para guardarlo.")
            return
        await db.commit()
        print(f"\nListo: {cambios} casos con título nuevo.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(titular("--aplicar" in sys.argv))
