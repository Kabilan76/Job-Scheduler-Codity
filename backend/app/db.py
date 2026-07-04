import socket
import urllib.parse
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from backend.app.config import settings

def is_postgres_available() -> bool:
    try:
        url = urllib.parse.urlparse(settings.DATABASE_URL)
        host = url.hostname or "localhost"
        port = url.port or 5432
        
        # If the environment specifies postgres but we can't open a connection, we fallback.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

# Dynamically decide DB URL and capabilities
IS_POSTGRES = is_postgres_available()

if IS_POSTGRES:
    DATABASE_URL = settings.DATABASE_URL
    SYNC_DATABASE_URL = settings.SYNC_DATABASE_URL
    print("[INFO] PostgreSQL connection successful. Using PG engine.")
else:
    DATABASE_URL = "sqlite+aiosqlite:///./scheduler.db"
    SYNC_DATABASE_URL = "sqlite:///./scheduler.db"
    print("[WARNING] PostgreSQL is not running. Falling back to SQLite.")

# Create async engine
engine_kwargs = {}
if IS_POSTGRES:
    engine_kwargs = {
        "pool_size": 20,
        "max_overflow": 10,
        "pool_pre_ping": True
    }
else:
    # SQLite setup
    engine_kwargs = {}

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    **engine_kwargs
)

# Create async session factory
async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Declarative base for models
Base = declarative_base()

# DB Dependency for endpoints
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            # Note: Commit is handled per-endpoint when required, but we commit automatically on success
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
