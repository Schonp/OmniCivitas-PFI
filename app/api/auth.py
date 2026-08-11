import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.security import (
    crear_access_token,
    crear_refresh_token,
    decodificar_token,
    verify_password,
)
from app.db.crud.usuarios import (
    contar_usuarios,
    crear_usuario,
    obtener_usuario_por_email,
    obtener_usuario_por_id,
)
from app.db.models import RolUsuario, Usuario
from app.db.session import get_db
from app.schemas.auth import LoginRequest, RefreshRequest, Token
from app.schemas.usuario import UsuarioCreate, UsuarioOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

_oauth2_opcional = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


@router.post("/login", response_model=Token)
async def login(datos: LoginRequest, db: AsyncSession = Depends(get_db)) -> Token:
    usuario = await obtener_usuario_por_email(db, datos.email)
    if (
        usuario is None
        or not usuario.activo
        or not verify_password(datos.password, usuario.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Email o contraseña inválidos"
        )

    return Token(
        access_token=crear_access_token(str(usuario.id), usuario.rol.value),
        refresh_token=crear_refresh_token(str(usuario.id), usuario.rol.value),
    )


@router.post("/refresh", response_model=Token)
async def refresh(datos: RefreshRequest, db: AsyncSession = Depends(get_db)) -> Token:
    try:
        payload = decodificar_token(datos.refresh_token)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido"
        ) from exc

    if payload.get("tipo") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido")

    usuario = await obtener_usuario_por_id(db, payload["sub"])
    if usuario is None or not usuario.activo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido")

    return Token(
        access_token=crear_access_token(str(usuario.id), usuario.rol.value),
        refresh_token=crear_refresh_token(str(usuario.id), usuario.rol.value),
    )


@router.get("/perfil", response_model=UsuarioOut)
async def perfil(usuario_actual: Usuario = Depends(get_current_user)) -> UsuarioOut:
    """El panel lo usa para mostrar quién está operando y validar el token guardado."""
    return usuario_actual


@router.post("/registrar", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
async def registrar_usuario(
    datos: UsuarioCreate,
    token: str | None = Depends(_oauth2_opcional),
    db: AsyncSession = Depends(get_db),
) -> UsuarioOut:
    """Crea un usuario (operador/supervisor/admin).

    Bootstrap: si todavía no existe ningún usuario, se permite crear el
    primero sin autenticación y siempre como admin. Una vez que existe al
    menos un usuario, sólo un admin autenticado puede crear más.
    """
    if await contar_usuarios(db) == 0:
        datos = datos.model_copy(update={"rol": RolUsuario.supervisor})
    else:
        if token is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Requiere autenticación"
            )
        try:
            payload = decodificar_token(token)
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido"
            ) from exc

        usuario_actual = await obtener_usuario_por_id(db, payload["sub"])
        if usuario_actual is None or usuario_actual.rol != RolUsuario.supervisor:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo un supervisor puede crear usuarios",
            )

    if await obtener_usuario_por_email(db, datos.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El email ya está registrado"
        )

    return await crear_usuario(db, datos)
