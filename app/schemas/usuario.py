import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import RolUsuario


class UsuarioCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    nombre: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8)
    rol: RolUsuario = RolUsuario.operador


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    nombre: str
    rol: RolUsuario
    activo: bool
