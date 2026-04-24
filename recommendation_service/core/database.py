from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager
import asyncpg
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
    async_scoped_session
)
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool
from sqlalchemy import text
from asyncio import current_task
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import settings

logger = structlog.get_logger()

class DatabaseManager:
    """Manages database connections with connection pooling"""
    
    def __init__(self):
        self.engine: Optional[AsyncEngine] = None
        self.async_session_maker: Optional[async_sessionmaker[AsyncSession]] = None
        self._session_factory = None
        
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30)
    )
    async def initialize(self):
        """Initialize database engine with connection pooling"""
        try:
            # Convert database URL to asyncpg format
            database_url = str(settings.database_url)
            
            # For Docker development, ensure we're using the service name
            if settings.environment == "development" and "localhost" in database_url:
                database_url = database_url.replace("localhost", "postgres")
                logger.info("using_docker_db_host", host="postgres")
            
            # Create engine based on environment
            if settings.environment == "production":
                # Production: Use connection pooling
                self.engine = create_async_engine(
                    database_url,
                    pool_size=settings.database_pool_size,
                    max_overflow=settings.database_max_overflow,
                    pool_timeout=settings.database_pool_timeout,
                    pool_pre_ping=settings.database_pool_pre_ping,
                    poolclass=AsyncAdaptedQueuePool,
                    echo=settings.debug,
                    echo_pool=settings.debug,
                    future=True,
                    connect_args={
                        "server_settings": {"application_name": "serveease_recommendation"}
                    }
                )
            else:
                # Development: Use NullPool with connection retry
                self.engine = create_async_engine(
                    database_url,
                    poolclass=NullPool,
                    echo=settings.debug,
                    echo_pool=settings.debug,
                    future=True,
                    connect_args={
                        "server_settings": {"application_name": "serveease_recommendation"},
                        "timeout": 60,
                        "command_timeout": 60
                    }
                )
            
            # Test connection with retry - FIXED: Use text() for raw SQL
            try:
                async with self.engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                    await conn.commit()
                logger.info("database_connection_successful")
            except Exception as conn_err:
                logger.error("database_connection_test_failed", error=str(conn_err), exc_info=True)
                raise
            
            # Create session factory
            self.async_session_maker = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False
            )
            
            logger.info(
                "database_initialized",
                environment=settings.environment,
                pooling_enabled=settings.environment == "production",
                database_url=database_url.replace("postgresql://", "postgresql://***:***@")
            )
            
        except Exception as e:
            logger.error("database_initialization_failed", error=str(e), exc_info=True)
            raise
    
    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get database session with automatic cleanup"""
        if not self.async_session_maker:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        
        session = self.async_session_maker()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("database_session_error", error=str(e), exc_info=True)
            raise
        finally:
            await session.close()
    
    async def get_scoped_session(self) -> async_scoped_session[AsyncSession]:
        """Get scoped session for request-level caching"""
        if not self._session_factory:
            if not self.async_session_maker:
                raise RuntimeError("Database not initialized. Call initialize() first.")
            self._session_factory = async_scoped_session(
                self.async_session_maker,
                scopefunc=current_task
            )
        return self._session_factory()
    
    async def close(self):
        """Close all database connections"""
        if self.engine:
            await self.engine.dispose()
            logger.info("database_connections_closed")

# Global database manager instance
db_manager = DatabaseManager()

# Dependency for FastAPI
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for getting database session.
    Usage: 
        async def endpoint(db: AsyncSession = Depends(get_db_session)):
            ...
    """
    async with db_manager.get_session() as session:
        yield session

async def get_db_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """Get raw asyncpg connection for PostGIS operations"""
    dsn = str(settings.database_url).replace("+asyncpg", "")
    if settings.environment == "development" and "localhost" in dsn:
        dsn = dsn.replace("localhost", "postgres")
    conn = await asyncpg.connect(dsn)
    try:
        yield conn
    finally:
        await conn.close()