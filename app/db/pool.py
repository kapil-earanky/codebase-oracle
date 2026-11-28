from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection, Error
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from app.config import get_settings
from app.db.models import DBHealthStatus

_HEALTH_QUERY = """
SELECT
    EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector'),
    to_regclass('public.code_chunks') IS NOT NULL;
"""


async def _configure_connection(conn: AsyncConnection[Any]) -> None:
    """Register pgvector adapters on each new pooled connection and leave it IDLE."""
    await register_vector_async(conn)
    await conn.commit()


async def check_db_health(
    pool: AsyncConnectionPool,
    *,
    timeout: float = 2.0,
) -> DBHealthStatus:
    """Verify PostgreSQL connectivity, pgvector extension, and code_chunks table."""
    try:
        async with pool.connection(timeout=timeout) as conn, conn.cursor() as cur:
            await cur.execute(_HEALTH_QUERY)
            row = await cur.fetchone()
            pgvector_installed = bool(row and row[0])
            code_chunks_exists = bool(row and row[1])
            return DBHealthStatus(
                healthy=pgvector_installed and code_chunks_exists,
                pgvector_installed=pgvector_installed,
                code_chunks_exists=code_chunks_exists,
            )
    except (PoolTimeout, Error) as exc:
        return DBHealthStatus(
            healthy=False,
            pgvector_installed=False,
            code_chunks_exists=False,
            error=str(exc),
        )


@asynccontextmanager
async def create_pool(
    dsn: str | None = None,
    *,
    min_size: int = 2,
    max_size: int = 10,
    timeout: float = 5.0,
) -> AsyncGenerator[AsyncConnectionPool, None]:
    """Open and yield an async PostgreSQL connection pool with pgvector registered."""
    pool = AsyncConnectionPool(
        conninfo=dsn or get_settings().postgres.dsn,
        open=False,
        min_size=min_size,
        max_size=max_size,
        timeout=timeout,
        configure=_configure_connection,
        connection_class=AsyncConnection,
    )
    try:
        await pool.open()
        yield pool
    finally:
        await pool.close()
