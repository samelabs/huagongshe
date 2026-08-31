"""Database connection management."""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from .config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_timeout=15,
    echo=False,
    connect_args={
        "ssl": False,
        "server_settings": {
            "application_name": "huagongshe-api",
            "statement_timeout": "8000",
            "idle_in_transaction_session_timeout": "15000",
        },
    },
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI dependency: yields a database session."""
    async with async_session() as session:
        yield session
