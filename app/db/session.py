from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# pool_pre_ping: el poller de correo vive horas entre mensajes y Postgres cierra
# las conexiones ociosas. Sin el chequeo previo, el pool entrega una conexión ya
# muerta y la primera consulta falla con "connection is closed", que en el ciclo
# del buzón significa un correo del ciudadano que se queda sin respuesta.
# pool_recycle las rota antes de que el servidor las cierre por su cuenta.
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=1800,
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
