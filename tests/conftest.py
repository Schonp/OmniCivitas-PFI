from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import crear_access_token, hash_password
from app.db.models import Base, RolUsuario, Usuario
from app.db.session import get_db
from app.main import app


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
async def usuario_admin(db_session: AsyncSession) -> Usuario:
    usuario = Usuario(
        email="admin@omnicivitas.test",
        nombre="Admin de prueba",
        hashed_password=hash_password("password123"),
        rol=RolUsuario.admin,
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
