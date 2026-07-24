import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.core.security import decrypt_str, encrypt_str


class Base(DeclarativeBase):
    pass


class EncryptedString(TypeDecorator):
    """Encripta con Fernet antes de persistir; desencripta al leer (Ley 25.326)."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        return None if value is None else encrypt_str(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        return None if value is None else decrypt_str(value)


class TipoCaso(str, enum.Enum):
    consulta = "consulta"
    reclamo = "reclamo"
    reserva = "reserva"
    tramite = "tramite"


class EstadoCaso(str, enum.Enum):
    abierto = "abierto"
    en_progreso = "en_progreso"
    escalado = "escalado"
    cerrado = "cerrado"


class Canal(str, enum.Enum):
    whatsapp = "whatsapp"
    sms = "sms"
    email = "email"
    voz = "voz"
    web = "web"


class ActorInteraccion(str, enum.Enum):
    ciudadano = "ciudadano"
    agente_ia = "agente_ia"
    operador = "operador"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Ciudadano(Base):
    __tablename__ = "ciudadanos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    documento: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(EncryptedString(500), nullable=True)
    telefono: Mapped[str | None] = mapped_column(EncryptedString(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    casos: Mapped[list["Caso"]] = relationship(back_populates="ciudadano")


class Caso(Base):
    __tablename__ = "casos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    ciudadano_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ciudadanos.id"), index=True)
    tipo: Mapped[TipoCaso] = mapped_column(SAEnum(TipoCaso, name="tipo_caso"))
    estado: Mapped[EstadoCaso] = mapped_column(
        SAEnum(EstadoCaso, name="estado_caso"), default=EstadoCaso.abierto
    )
    canal_origen: Mapped[Canal] = mapped_column(SAEnum(Canal, name="canal"))
    canal_actual: Mapped[Canal] = mapped_column(SAEnum(Canal, name="canal"))
    # Sin FK todavía: la tabla de operadores/usuarios se agrega en la Fase 2 (Auth).
    operador_asignado_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ciudadano: Mapped["Ciudadano"] = relationship(back_populates="casos")
    interacciones: Mapped[list["Interaccion"]] = relationship(back_populates="caso")
    auditorias: Mapped[list["Auditoria"]] = relationship(back_populates="caso")


class Interaccion(Base):
    __tablename__ = "interacciones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    caso_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("casos.id"), index=True)
    contenido: Mapped[str] = mapped_column(Text)
    canal: Mapped[Canal] = mapped_column(SAEnum(Canal, name="canal"))
    actor: Mapped[ActorInteraccion] = mapped_column(SAEnum(ActorInteraccion, name="actor_interaccion"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    caso: Mapped["Caso"] = relationship(back_populates="interacciones")


class Auditoria(Base):
    __tablename__ = "auditorias"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    caso_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("casos.id"), index=True)
    accion: Mapped[str] = mapped_column(String(100))
    actor: Mapped[str] = mapped_column(String(200))
    actor_tipo: Mapped[ActorInteraccion] = mapped_column(SAEnum(ActorInteraccion, name="actor_interaccion"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    caso: Mapped["Caso"] = relationship(back_populates="auditorias")
