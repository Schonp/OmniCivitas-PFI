"""Alta de usuarios del panel.

Uso:  python -m scripts.crear_usuario <email> <nombre> <password> <supervisor|operador>

Si el email ya existe, actualiza el rol y la contraseña en lugar de fallar.
"""

import asyncio
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import RolUsuario, Usuario
from app.db.session import async_session_factory


async def crear_usuario(email: str, nombre: str, password: str, rol: RolUsuario) -> str:
    async with async_session_factory() as db:
        existente = (
            await db.execute(select(Usuario).where(Usuario.email == email))
        ).scalars().first()

        if existente is not None:
            existente.nombre = nombre
            existente.hashed_password = hash_password(password)
            existente.rol = rol
            existente.activo = True
            await db.commit()
            return f"Usuario actualizado: {email} ({rol.value})"

        db.add(
            Usuario(
                email=email,
                nombre=nombre,
                hashed_password=hash_password(password),
                rol=rol,
            )
        )
        await db.commit()
        return f"Usuario creado: {email} ({rol.value})"


def main() -> None:
    if len(sys.argv) != 5:
        print(__doc__)
        raise SystemExit(1)

    email, nombre, password, rol_texto = sys.argv[1:5]
    try:
        rol = RolUsuario(rol_texto)
    except ValueError:
        validos = ", ".join(r.value for r in RolUsuario)
        print(f"Rol inválido: {rol_texto}. Opciones: {validos}")
        raise SystemExit(1) from None

    print(asyncio.run(crear_usuario(email, nombre, password, rol)))


if __name__ == "__main__":
    main()
