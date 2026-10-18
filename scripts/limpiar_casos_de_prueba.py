"""Borra los casos de prueba de un ciudadano para dejar la base lista para grabar.

Solo toca los casos del documento indicado: los datos sembrados por seed_demo
(los otros vecinos, que hacen que el panel se vea poblado) quedan intactos.

Uso:  python -m scripts.limpiar_casos_de_prueba 30123456            (simulacro)
      python -m scripts.limpiar_casos_de_prueba 30123456 --borrar   (borra)

Por qué importa antes de una demo cross-canal: `contexto` engancha el caso
abierto más reciente del ciudadano. Con varios casos abiertos de temas cruzados,
el mensaje que se manda en cámara puede caer en el caso equivocado.
"""

import asyncio
import sys

from sqlalchemy import delete, func, select

from app.db.models import Auditoria, Caso, Ciudadano, Interaccion, Reserva
from app.db.session import async_session_factory


async def limpiar(documento: str, borrar: bool) -> None:
    async with async_session_factory() as db:
        ciudadano = (
            await db.execute(select(Ciudadano).where(Ciudadano.documento == documento))
        ).scalar_one_or_none()
        if ciudadano is None:
            print(f"No hay ningún ciudadano con documento {documento}.")
            return

        ids = list(
            (
                await db.execute(select(Caso.id).where(Caso.ciudadano_id == ciudadano.id))
            ).scalars()
        )
        if not ids:
            print(f"{ciudadano.nombre} no tiene casos: la base ya está limpia.")
            return

        async def contar(modelo) -> int:
            return (
                await db.execute(
                    select(func.count()).select_from(modelo).where(modelo.caso_id.in_(ids))
                )
            ).scalar_one()

        interacciones = await contar(Interaccion)
        auditorias = await contar(Auditoria)
        reservas = await contar(Reserva)

        print(f"Ciudadano: {ciudadano.nombre} (documento {documento})")
        print(f"  casos.........: {len(ids)}")
        print(f"  interacciones.: {interacciones}")
        print(f"  auditorías....: {auditorias}")
        print(f"  reservas......: {reservas}")

        if not borrar:
            print("\nSimulacro: no se borró nada. Repetí con --borrar para hacerlo.")
            return

        # Primero lo que referencia al caso, después el caso.
        for modelo in (Reserva, Interaccion, Auditoria):
            await db.execute(delete(modelo).where(modelo.caso_id.in_(ids)))
        await db.execute(delete(Caso).where(Caso.id.in_(ids)))
        await db.commit()
        print(f"\nBorrados {len(ids)} casos y todo lo que colgaba de ellos.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(limpiar(sys.argv[1], "--borrar" in sys.argv))
