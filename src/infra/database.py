"""
Async SQLAlchemy engine + session factory.

pool_size=20, max_overflow=10 (conforme prompt.md).
Nunca usa sync ORM nem greenlets.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.config import settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base declarativa para todos os modelos ORM."""
    pass


engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    echo=settings.debug,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_session() -> AsyncSession:
    """Dependency FastAPI → sessão com commit automático no final."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            yield session


async def connect() -> None:
    """Verifica conectividade com o banco durante o lifespan startup."""
    async with engine.begin() as conn:
        await conn.run_sync(lambda _: None)
    log.info("Conexão com o banco de dados estabelecida")


async def disconnect() -> None:
    """Fecha o pool de conexões durante o lifespan shutdown."""
    await engine.dispose()
    log.info("Pool de conexões com o banco encerrado")
