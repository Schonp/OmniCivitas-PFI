import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext

from app.core.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(password, hashed_password)


def _crear_token(sub: str, rol: str, tipo: Literal["access", "refresh"], expira_en: timedelta) -> str:
    ahora = datetime.now(timezone.utc)
    payload = {"sub": sub, "rol": rol, "tipo": tipo, "iat": ahora, "exp": ahora + expira_en}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=JWT_ALGORITHM)


def crear_access_token(usuario_id: str, rol: str) -> str:
    expira_en = timedelta(hours=settings.jwt_access_token_expire_hours)
    return _crear_token(usuario_id, rol, "access", expira_en)


def crear_refresh_token(usuario_id: str, rol: str) -> str:
    expira_en = timedelta(days=settings.jwt_refresh_token_expire_days)
    return _crear_token(usuario_id, rol, "refresh", expira_en)


def crear_chat_token(ciudadano_id: str) -> str:
    """Sesión del chat web: identifica a un ciudadano, no a un usuario del panel.
    Sin rol — nunca da acceso a los endpoints internos (`tipo != "access"`)."""
    ahora = datetime.now(timezone.utc)
    expira_en = timedelta(hours=settings.chat_session_expire_hours)
    payload = {"sub": ciudadano_id, "tipo": "chat", "iat": ahora, "exp": ahora + expira_en}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=JWT_ALGORITHM)


def decodificar_token(token: str) -> dict[str, Any]:
    """Levanta jwt.PyJWTError (o subclases) si el token es inválido o expiró."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[JWT_ALGORITHM])


def _get_fernet() -> Fernet:
    if not settings.fernet_key:
        raise RuntimeError("FERNET_KEY no está configurada")
    return Fernet(settings.fernet_key.encode())


def hash_lookup_str(value: str) -> str:
    """HMAC-SHA256 determinístico para lookup por igualdad de datos cifrados.

    Normaliza (strip + lower) para que el mismo contacto siempre produzca el
    mismo hash. No es reversible: solo sirve para buscar, no para recuperar.
    """
    if not settings.hash_lookup_key:
        raise RuntimeError("HASH_LOOKUP_KEY no está configurada")
    normalizado = value.strip().lower()
    return hmac.new(
        settings.hash_lookup_key.encode(), normalizado.encode(), hashlib.sha256
    ).hexdigest()


def encrypt_str(value: str) -> str:
    """Encripta un dato de contacto antes de persistirlo."""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_str(value: str) -> str:
    """Desencripta un dato de contacto al momento de usarlo."""
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("No se pudo desencriptar el valor: token inválido") from exc
