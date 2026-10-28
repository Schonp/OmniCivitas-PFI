import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Time,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates
from sqlalchemy.types import TypeDecorator

from app.core.security import decrypt_str, encrypt_str, hash_lookup_str


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


class EstadoReserva(str, enum.Enum):
    """Solo una reserva `confirmada` ocupa cupo: cancelarla lo libera."""

    confirmada = "confirmada"
    cancelada = "cancelada"
    atendida = "atendida"
    ausente = "ausente"


class Canal(str, enum.Enum):
    """Canales del prototipo: WhatsApp, email y llamada telefónica.

    Ni `sms` ni `web` existen más en el tipo enum de Postgres: `sms` quedó
    huérfano desde el día cero (migración `c6730a402335`) y `web`, el chat
    propio que sostuvo la demo hasta tener Twilio e IMAP/SMTP, se retiró en
    la migración `3b9e5d1f7a20`.
    """

    whatsapp = "whatsapp"
    email = "email"
    voz = "voz"


class ActorInteraccion(str, enum.Enum):
    ciudadano = "ciudadano"
    agente_ia = "agente_ia"
    operador = "operador"


class RolUsuario(str, enum.Enum):
    """Dos roles: el operador trabaja su propia bandeja, el supervisor ve todo
    el organismo y distribuye los casos."""

    operador = "operador"
    supervisor = "supervisor"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Ciudadano(Base):
    __tablename__ = "ciudadanos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    documento: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(EncryptedString(500), nullable=True)
    telefono: Mapped[str | None] = mapped_column(EncryptedString(500), nullable=True)
    # Hashes HMAC determinísticos: Fernet es aleatorio, sin esto no se puede
    # buscar un ciudadano por el teléfono/email que llega de un canal.
    email_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    telefono_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    casos: Mapped[list["Caso"]] = relationship(back_populates="ciudadano")

    @validates("email")
    def _sync_email_hash(self, key: str, value: str | None) -> str | None:
        self.email_hash = None if value is None else hash_lookup_str(value)
        return value

    @validates("telefono")
    def _sync_telefono_hash(self, key: str, value: str | None) -> str | None:
        self.telefono_hash = None if value is None else hash_lookup_str(value)
        return value


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    hashed_password: Mapped[str] = mapped_column(String(255))
    rol: Mapped[RolUsuario] = mapped_column(SAEnum(RolUsuario, name="rol_usuario"))
    activo: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    casos_asignados: Mapped[list["Caso"]] = relationship(back_populates="operador_asignado")


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
    operador_asignado_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("usuarios.id"), nullable=True
    )
    motivo_cierre: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Resumen generado por IA para que el operador retome el caso sin leer toda
    # la conversación. Se regenera a pedido desde el panel.
    resumen_ia: Mapped[str | None] = mapped_column(Text, nullable=True)
    resumen_ia_generado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Asunto del correo con el que se abrió el caso. Se guarda para que la
    # respuesta del operador continúe el mismo hilo en la bandeja del ciudadano
    # en vez de aparecer como un mensaje suelto.
    asunto: Mapped[str | None] = mapped_column(String(300), nullable=True)

    ciudadano: Mapped["Ciudadano"] = relationship(back_populates="casos")

    @property
    def referencia(self) -> str:
        """Identificador legible para el ciudadano. El UUID es la clave interna;
        mandárselo en un correo o un WhatsApp no le sirve a nadie y no es lo que
        haría un organismo. Se deriva del propio id, así que no hace falta
        columna nueva ni secuencia."""
        prefijos = {
            TipoCaso.reclamo: "REC",
            TipoCaso.reserva: "RES",
            TipoCaso.consulta: "CON",
            TipoCaso.tramite: "TRA",
        }
        return f"{prefijos[self.tipo]}-{str(self.id)[:8].upper()}"

    @property
    def en_manos_humanas(self) -> bool:
        """El caso ya lo tiene una persona: derivado esperando que lo tomen, o
        tomado por un operador. Mientras esté así el agente no lo retoma, y lo
        que el caso espera es la respuesta del operador, no la del agente."""
        return (
            self.estado in (EstadoCaso.escalado, EstadoCaso.en_progreso)
            or self.operador_asignado_id is not None
        )
    interacciones: Mapped[list["Interaccion"]] = relationship(back_populates="caso")
    auditorias: Mapped[list["Auditoria"]] = relationship(back_populates="caso")
    operador_asignado: Mapped["Usuario | None"] = relationship(back_populates="casos_asignados")


class Interaccion(Base):
    __tablename__ = "interacciones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    caso_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("casos.id"), index=True)
    contenido: Mapped[str] = mapped_column(Text)
    canal: Mapped[Canal] = mapped_column(SAEnum(Canal, name="canal"))
    actor: Mapped[ActorInteraccion] = mapped_column(SAEnum(ActorInteraccion, name="actor_interaccion"))
    # Nota interna: queda en el caso para el organismo, nunca se le muestra al
    # ciudadano ni sale por ningún canal.
    interna: Mapped[bool] = mapped_column(default=False, server_default="false")
    # clock_timestamp() y no now(): now() es constante dentro de la transacción,
    # y el mensaje del ciudadano y la respuesta del agente se guardan en la misma.
    # Con la misma hora el panel mostraría la conversación en orden arbitrario.
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )

    caso: Mapped["Caso"] = relationship(back_populates="interacciones")


class Auditoria(Base):
    __tablename__ = "auditorias"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    caso_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("casos.id"), index=True)
    accion: Mapped[str] = mapped_column(String(100))
    actor: Mapped[str] = mapped_column(String(200))
    actor_tipo: Mapped[ActorInteraccion] = mapped_column(SAEnum(ActorInteraccion, name="actor_interaccion"))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    caso: Mapped["Caso"] = relationship(back_populates="auditorias")


class Turno(Base):
    """Agenda de turnos que el organismo ofrece (ej. renovación de licencia).
    El agente reserva sobre estas agendas; el panel las muestra para verificar
    que las reservas del agente sean correctas."""

    __tablename__ = "turnos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    nombre: Mapped[str] = mapped_column(String(200), unique=True)
    descripcion: Mapped[str] = mapped_column(Text)
    sede: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # La grilla de la agenda, como en cualquier turnero: qué días atiende, de
    # qué hora a qué hora, cada cuánto empieza un turno y cuántas personas se
    # atienden en el mismo horario (puestos o ventanillas en paralelo).
    # Días con la numeración de Python: 0 es lunes, 6 es domingo.
    dias_atencion: Mapped[str] = mapped_column(String(20), default="0,1,2,3,4", server_default="0,1,2,3,4")
    hora_apertura: Mapped[time] = mapped_column(Time, default=time(8, 0), server_default="08:00")
    hora_cierre: Mapped[time] = mapped_column(Time, default=time(14, 0), server_default="14:00")
    duracion_minutos: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    cupos_por_horario: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    anticipacion_maxima_dias: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    reservas: Mapped[list["Reserva"]] = relationship(back_populates="turno")

    @property
    def dias(self) -> list[int]:
        return [int(dia) for dia in self.dias_atencion.split(",") if dia.strip()]


class Reserva(Base):
    __tablename__ = "reservas"
    __table_args__ = (
        # Un ciudadano no puede tener dos turnos vigentes en el mismo momento,
        # aunque sean de agendas distintas. Lo garantiza la base y no solo el
        # código: dos pedidos simultáneos no pueden colarse los dos.
        Index(
            "ux_reserva_ciudadano_horario",
            "ciudadano_id",
            "fecha_hora",
            unique=True,
            postgresql_where=text("estado = 'confirmada'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    turno_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("turnos.id"), index=True)
    caso_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("casos.id"), index=True)
    ciudadano_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ciudadanos.id"), index=True)
    fecha_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    estado: Mapped[EstadoReserva] = mapped_column(
        SAEnum(EstadoReserva, name="estado_reserva"),
        default=EstadoReserva.confirmada,
        server_default=EstadoReserva.confirmada.value,
    )
    motivo_cancelacion: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cancelada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Se marca solo si el recordatorio salió de verdad: si el envío falla, el
    # próximo envío de recordatorios lo vuelve a intentar.
    recordatorio_enviado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    turno: Mapped["Turno"] = relationship(back_populates="reservas")
    ciudadano: Mapped["Ciudadano"] = relationship()
    caso: Mapped["Caso"] = relationship()


class DiaBloqueado(Base):
    """Un día sin atención: un feriado, o una jornada en que una agenda no
    atiende (capacitación, mudanza de la sede). Sin agenda, vale para todas."""

    __tablename__ = "dias_bloqueados"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    turno_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("turnos.id", ondelete="CASCADE"), nullable=True, index=True
    )
    fecha: Mapped[date] = mapped_column(Date, index=True)
    motivo: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentoConocimiento(Base):
    """Base de conocimiento del organismo: texto que se le da como contexto a la
    IA para responder consultas (trámites, requisitos, horarios)."""

    __tablename__ = "documentos_conocimiento"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    titulo: Mapped[str] = mapped_column(String(200))
    contenido: Mapped[str] = mapped_column(Text)
    # Nombre del archivo original si se cargó por archivo; None si fue texto directo.
    nombre_archivo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Pauta general: una instrucción de comportamiento que el ejecutor recibe en
    # todas las conversaciones, no solo cuando el mensaje la menciona. El resto
    # de los documentos se recupera por relevancia.
    general: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GrupoReclamo(Base):
    """Agrupación de reclamos afines detectada por la IA. Se regenera completa en
    cada corrida: es una foto para el panel, no una entidad de gestión."""

    __tablename__ = "grupos_reclamos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tema: Mapped[str] = mapped_column(String(200))
    caso_ids: Mapped[list] = mapped_column(JSON)
    generado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
