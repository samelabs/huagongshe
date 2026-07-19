"""Database connection management."""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import event
from .config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_timeout=15,
    echo=False,
    connect_args={
        "ssl": False,
        "server_settings": {"statement_timeout": "8000"},
    },
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI dependency: yields a database session."""
    async with async_session() as session:
        yield session
