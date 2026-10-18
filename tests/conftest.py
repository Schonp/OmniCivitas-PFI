from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.graph import procesar_mensaje
from app.core.config import settings
from app.core.rate_limit import reset_rate_limit
from app.core.security import crear_access_token, hash_password
from app.db.models import Base, Ciudadano, RolUsuario, Usuario
from app.db.session import get_db
from app.main import app
from app.schemas.agente import ClasificacionIntent


@pytest.fixture
async def db_engine():
    # Function-scoped (no session-scoped): pytest.ini fija
    # asyncio_default_fixture_loop_scope=function, y un engine de vida más
    # larga que el loop de cada test rompe con ScopeMismatch.
    engine = create_async_engine(settings.test_database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def ciudadano(db_session: AsyncSession) -> Ciudadano:
    persona = Ciudadano(
        documento="12345678",
        nombre="Juan Pérez",
        email="juan.perez@test.com",
        telefono="+5491122334455",
    )
    db_session.add(persona)
    await db_session.commit()
    await db_session.refresh(persona)
    return persona


@pytest.fixture
async def usuario_admin(db_session: AsyncSession) -> Usuario:
    """Supervisor: ve todos los casos del organismo y los distribuye."""
    usuario = Usuario(
        email="admin@omnicivitas.test",
        nombre="Admin de prueba",
        hashed_password=hash_password("password123"),
        rol=RolUsuario.supervisor,
    )
    db_session.add(usuario)
    await db_session.commit()
    await db_session.refresh(usuario)
    return usuario


@pytest.fixture
async def usuario_operador(db_session: AsyncSession) -> Usuario:
    usuario = Usuario(
        email="operador@omnicivitas.test",
        nombre="Operador de prueba",
        hashed_password=hash_password("password123"),
        rol=RolUsuario.operador,
    )
    db_session.add(usuario)
    await db_session.commit()
    await db_session.refresh(usuario)
    return usuario


@pytest.fixture
def token_admin(usuario_admin: Usuario) -> str:
    return crear_access_token(str(usuario_admin.id), usuario_admin.rol.value)


@pytest.fixture
def auth_headers(token_admin: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_admin}"}


@pytest.fixture
def headers_operador(usuario_operador: Usuario) -> dict[str, str]:
    token = crear_access_token(str(usuario_operador.id), usuario_operador.rol.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def rate_limit_limpio():
    # El contador vive en memoria del proceso: sin esto, los hits de un test
    # se acumulan en el siguiente.
    reset_rate_limit()
    yield
    reset_rate_limit()


@pytest.fixture
def mock_llms(mocker):
    """Mockea los dos LLM del grafo. `clasificaciones` y `respuestas_ejecutor`
    aceptan una lista para cubrir varios mensajes en el mismo test."""

    def _configurar(
        clasificaciones: ClasificacionIntent | list[ClasificacionIntent],
        respuestas_ejecutor: list[AIMessage] | None = None,
        resumen_escalado: str = "Resumen para operador",
    ) -> None:
        if isinstance(clasificaciones, ClasificacionIntent):
            clasificaciones = [clasificaciones]

        mock_intake = MagicMock()
        mock_intake.with_structured_output.return_value.ainvoke = AsyncMock(
            side_effect=list(clasificaciones)
        )
        # El nodo escalado usa el mismo LLM barato para el resumen del operador.
        mock_intake.ainvoke = AsyncMock(return_value=AIMessage(content=resumen_escalado))
        mocker.patch("app.agents.llm.get_llm_intake", return_value=mock_intake)

        mock_ejecutor = MagicMock()
        if respuestas_ejecutor is not None:
            mock_ejecutor.bind_tools.return_value.ainvoke = AsyncMock(
                side_effect=list(respuestas_ejecutor)
            )
        mocker.patch("app.agents.llm.get_llm_ejecutor", return_value=mock_ejecutor)

    return _configurar


@pytest.fixture
def checkpointer_en_memoria(mocker) -> InMemorySaver:
    """Los canales llaman al orquestador sin checkpointer (usa Postgres en runtime).
    En tests se inyecta uno en memoria para no depender de ese setup."""
    saver = InMemorySaver()

    async def _procesar(db, **kwargs):
        return await procesar_mensaje(db, **kwargs, checkpointer=saver)

    for canal in ("web", "whatsapp", "email"):
        mocker.patch(f"app.channels.{canal}.procesar_mensaje", side_effect=_procesar)
    return saver
