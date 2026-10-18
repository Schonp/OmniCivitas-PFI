"""Ciclo del canal de correo: lee el buzón, pasa cada mensaje por el
orquestador y responde al ciudadano.

El correo no tiene webhook como WhatsApp, así que el canal funciona por
polling. Este script corre aparte de la API para poder arrancarlo y pararlo
durante una demo sin tocar el servidor.

Corre de a uno: si ya hay otro poller vivo, este avisa y se va sin tocar el
buzón. Dos procesos sobre la misma casilla se pisan y el ciudadano recibe la
respuesta del agente por duplicado.

Uso:  python -m scripts.revisar_correo            (ciclo continuo, cada 15 s)
      python -m scripts.revisar_correo --una-vez  (una sola pasada)
"""

import argparse
import asyncio
import logging
import sys

from app.agents.graph import cerrar_checkpointer, iniciar_checkpointer
from app.channels import email as canal_email
from app.core.instance_lock import InstanciaEnUso, instancia_unica
from app.db.session import async_session_factory

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s"
)
logger = logging.getLogger("revisar_correo")

INTERVALO_SEGUNDOS = 15
CANDADO = "revisar-correo"


async def _una_pasada() -> int:
    async with async_session_factory() as db:
        return await canal_email.procesar_buzon(db)


async def main(una_vez: bool, intervalo: int) -> None:
    # El grafo necesita el checkpointer inicializado, igual que la API.
    await iniciar_checkpointer()
    try:
        while True:
            try:
                procesados = await _una_pasada()
                if procesados:
                    logger.info("correos procesados: %s", procesados)
                else:
                    logger.debug("buzón sin correos nuevos")
            except Exception:
                logger.exception("falló la pasada por el buzón, se reintenta")

            if una_vez:
                return
            await asyncio.sleep(intervalo)
    finally:
        await cerrar_checkpointer()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Canal de correo por polling")
    parser.add_argument(
        "--una-vez", action="store_true", help="procesa el buzón una sola vez y termina"
    )
    parser.add_argument(
        "--intervalo",
        type=int,
        default=INTERVALO_SEGUNDOS,
        help=f"segundos entre pasadas (por defecto {INTERVALO_SEGUNDOS})",
    )
    args = parser.parse_args()
    # El checkpointer usa psycopg async, que en Windows no funciona con el
    # event loop Proactor (el default): el pool queda esperando y expira.
    # En el contenedor corre Linux, por eso esto solo hace falta acá.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        # El candado se toma antes de abrir el checkpointer y el pool: si ya hay
        # otro poller vivo, este no llega a tocar ni la base ni el buzón.
        with instancia_unica(CANDADO):
            asyncio.run(main(args.una_vez, args.intervalo))
    except InstanciaEnUso as error:
        logger.error("%s", error)
        logger.error(
            "No se arranca: dos pollers sobre la misma casilla le contestan dos "
            "veces al ciudadano. Pará el otro proceso, o seguí con el que ya corre."
        )
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\nCiclo detenido.")
