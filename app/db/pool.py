from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection, Error
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from app.config import get_settings
from app.db.models import DBHealthStatus


async def check_db_health(pool: AsyncConnectionPool) -> DBHealthStatus:
    # Acquire a connection from the pool
    pg_vector_installed = False
    code_chunks_exists = False
    code_chunks_table_name = "code_chunks"
    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            # Execute your SQL query
            await cur.execute(
                "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = %s);",
                (code_chunks_table_name,),
            )
            result = await cur.fetchone()
            if result:
                code_chunks_exists = bool(result[0])
            await cur.execute(
                "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
            )
            result = await cur.fetchone()
            if result:
                pg_vector_installed = bool(result[0])
            return DBHealthStatus(
                healthy=pg_vector_installed and code_chunks_exists,
                pgvector_installed=pg_vector_installed,
                code_chunks_exists=code_chunks_exists,
            )
    # The transaction automatically commits here if successful,
    # or rolls back if an exception occurs inside the block.
    except (PoolTimeout, Error) as e:
        return DBHealthStatus(
            healthy=False,
            pgvector_installed=pg_vector_installed,
            code_chunks_exists=code_chunks_exists,
            error=str(e),
        )


async def configure_vector(conn: AsyncConnection[Any]) -> None:
    await register_vector_async(conn)
    await conn.commit()


@asynccontextmanager
async def create_pool() -> AsyncGenerator[AsyncConnectionPool, None]:
    pool = AsyncConnectionPool(
        conninfo=get_settings().postgres.dsn,
        open=False,
        min_size=2,  # Minimum connections to maintain
        max_size=10,  # Maximum connection capacity
        timeout=5.0,
        configure=configure_vector,
        connection_class=AsyncConnection,
    )
    try:
        await pool.open()
        yield pool
    finally:
        await pool.close()
