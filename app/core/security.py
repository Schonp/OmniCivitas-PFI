from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _get_fernet() -> Fernet:
    if not settings.fernet_key:
        raise RuntimeError("FERNET_KEY no está configurada")
    return Fernet(settings.fernet_key.encode())


def encrypt_str(value: str) -> str:
    """Encripta un dato de contacto antes de persistirlo."""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_str(value: str) -> str:
    """Desencripta un dato de contacto al momento de usarlo."""
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("No se pudo desencriptar el valor: token inválido") from exc
