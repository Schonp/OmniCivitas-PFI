"""Borra todo lo de un vecino para empezar de cero: sus registros, sus casos y
la memoria de sus conversaciones.

Sirve para dejar la base lista antes de una demo o una grabación, cuando las
pruebas dejaron registros del vecino de prueba. A diferencia de
`limpiar_casos_de_prueba` (que busca solo por DNI y deja el registro), este:

- encuentra al vecino por DNI, por teléfono y por correo, y en todos los
  registros que haya: una prueba con un DNI mal escrito, o con el celular en el
  formato viejo (sin el 9), deja registros sueltos;
- borra el registro del ciudadano, no solo sus casos;
- borra la memoria de las conversaciones (los hilos del checkpointer), tanto la
  de cada caso como la provisoria de antes de abrir caso. Sin eso, el agente
  podía retomar una conversación vieja.

Por defecto solo muestra qué borraría. Borra recién con --borrar.

Uso:
    python -m scripts.borrar_vecino --dni 30123456 --telefono +5491155550123
    python -m scripts.borrar_vecino --dni 30123456 --telefono +5491155550123 --borrar
    python -m scripts.borrar_vecino --email vecina@correo.com --borrar
"""

import argparse
import asyncio
import sys

from sqlalchemy import delete, func, or_, select, text

from app.channels.whatsapp import normalizar_telefono
from app.core.security import hash_lookup_str
from app.db.models import Auditoria, Caso, Ciudadano, Interaccion, Reserva
from app.db.session import async_session_factory

CANALES = ("whatsapp", "voz", "email")
TABLAS_DE_MEMORIA = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")


def formas_del_telefono(telefono: str) -> set[str]:
    """El número como se guarda hoy (+549...) y como se guardaba antes de
    unificar los formatos (+54... sin el 9), para encontrar registros viejos."""
    actual = normalizar_telefono(telefono)
    formas = {actual}
    if actual.startswith("+549"):
        formas.add("+54" + actual[len("+549"):])
    return formas


async def borrar(dni: str | None, telefono: str | None, email: str | None, confirmar: bool) -> None:
    telefonos = formas_del_telefono(telefono) if telefono else set()
    condiciones = []
    if dni:
        condiciones.append(Ciudadano.documento == dni)
    if telefonos:
        condiciones.append(Ciudadano.telefono_hash.in_([hash_lookup_str(t) for t in telefonos]))
    if email:
        condiciones.append(Ciudadano.email_hash == hash_lookup_str(email))

    async with async_session_factory() as db:
        ciudadanos = list((await db.execute(select(Ciudadano).where(or_(*condiciones)))).scalars().all())
        if not ciudadanos:
            print("No encontré ningún registro con esos datos: la base ya está limpia.")
            return

        ids_ciudadanos = [c.id for c in ciudadanos]
        ids_casos = list(
            (await db.execute(select(Caso.id).where(Caso.ciudadano_id.in_(ids_ciudadanos)))).scalars()
        )

        async def contar(modelo) -> int:
            if not ids_casos:
                return 0
            return (
                await db.execute(select(func.count()).select_from(modelo).where(modelo.caso_id.in_(ids_casos)))
            ).scalar_one()

        # La memoria de cada caso se guarda con el id del caso; la de antes de
        # abrir caso, con el canal y el contacto ("pre:whatsapp:+549...").
        hilos = [str(caso_id) for caso_id in ids_casos]
        hilos += [f"pre:{canal}:{t}" for canal in CANALES for t in telefonos]
        if email:
            hilos += [f"pre:email:{email}", f"pre:email:{email.lower()}"]

        print("Registros encontrados:")
        for ciudadano in ciudadanos:
            print(f"  - {ciudadano.nombre} (documento {ciudadano.documento})")
        print(f"  casos.........: {len(ids_casos)}")
        print(f"  mensajes......: {await contar(Interaccion)}")
        print(f"  auditorías....: {await contar(Auditoria)}")
        print(f"  turnos........: {await contar(Reserva)}")

        if not confirmar:
            print("\nSimulacro: no se borró nada. Repetí el comando con --borrar para hacerlo.")
            return

        if ids_casos:
            # Primero lo que cuelga de los casos, después los casos.
            for modelo in (Reserva, Interaccion, Auditoria):
                await db.execute(delete(modelo).where(modelo.caso_id.in_(ids_casos)))
            await db.execute(delete(Caso).where(Caso.id.in_(ids_casos)))
        await db.execute(delete(Reserva).where(Reserva.ciudadano_id.in_(ids_ciudadanos)))
        await db.execute(delete(Ciudadano).where(Ciudadano.id.in_(ids_ciudadanos)))
        for tabla in TABLAS_DE_MEMORIA:
            await db.execute(text(f"DELETE FROM {tabla} WHERE thread_id = ANY(:hilos)"), {"hilos": hilos})
        await db.commit()
        print(f"\nListo: borré {len(ciudadanos)} registro(s), {len(ids_casos)} caso(s) y la memoria de sus conversaciones.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Borra todo lo de un vecino para empezar de cero.")
    parser.add_argument("--dni", help="Documento, sin puntos (ej. 30123456).")
    parser.add_argument("--telefono", help="Celular con código de país (ej. +5491155550123).")
    parser.add_argument("--email", help="Correo del vecino.")
    parser.add_argument("--borrar", action="store_true", help="Borra de verdad (sin esto, solo muestra).")
    args = parser.parse_args()
    if not (args.dni or args.telefono or args.email):
        parser.error("Indicá al menos --dni, --telefono o --email.")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(borrar(args.dni, args.telefono, args.email, args.borrar))


if __name__ == "__main__":
    main()
