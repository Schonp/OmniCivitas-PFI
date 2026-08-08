import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decodificar_token
from app.db.crud.ciudadanos import obtener_ciudadano_por_id
from app.db.crud.usuarios import obtener_usuario_por_id
from app.db.models import Ciudadano, RolUsuario, Usuario
from app.db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
chat_scheme = HTTPBearer(auto_error=False)

_CREDENCIALES_INVALIDAS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Credenciales inválidas",
    headers={"WWW-Authenticate": "Bearer"},
)

_SESION_CHAT_INVALIDA = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sesión de chat inválida o expirada",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Usuario:
    try:
        payload = decodificar_token(token)
    except jwt.PyJWTError as exc:
        raise _CREDENCIALES_INVALIDAS from exc

    if payload.get("tipo") != "access":
        raise _CREDENCIALES_INVALIDAS

    usuario = await obtener_usuario_por_id(db, payload["sub"])
    if usuario is None or not usuario.activo:
        raise _CREDENCIALES_INVALIDAS
    return usuario


async def get_ciudadano_actual(
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(chat_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Ciudadano:
    """Ciudadano detrás de una sesión del chat web. Sin esto, cualquiera con un
    email ajeno podría leer la conversación de otra persona (Ley 25.326)."""
    if credenciales is None:
        raise _SESION_CHAT_INVALIDA

    try:
        payload = decodificar_token(credenciales.credentials)
    except jwt.PyJWTError as exc:
        raise _SESION_CHAT_INVALIDA from exc

    if payload.get("tipo") != "chat":
        raise _SESION_CHAT_INVALIDA

    try:
        ciudadano_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise _SESION_CHAT_INVALIDA from exc

    ciudadano = await obtener_ciudadano_por_id(db, ciudadano_id)
    if ciudadano is None:
        raise _SESION_CHAT_INVALIDA
    return ciudadano


def requiere_rol(*roles: RolUsuario):
    async def dependency(usuario: Annotated[Usuario, Depends(get_current_user)]) -> Usuario:
        if usuario.rol not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permiso para esta acción",
            )
        return usuario

    return dependency
