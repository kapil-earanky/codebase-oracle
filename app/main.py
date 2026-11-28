import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from psycopg_pool import AsyncConnectionPool

from app.db.models import DBHealthStatus
from app.db.pool import check_db_health, create_pool

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application-wide async resources across FastAPI startup and shutdown."""
    logger.info("Starting Codebase Oracle...")
    async with create_pool() as pool:
        app.state.db_pool = pool
        yield
    logger.info("Shutting down Codebase Oracle...")


def get_db_pool(request: Request) -> AsyncConnectionPool:
    """FastAPI dependency returning the shared async PostgreSQL connection pool."""
    pool: AsyncConnectionPool = request.app.state.db_pool
    return pool


app = FastAPI(title="Codebase Oracle", lifespan=lifespan)


@app.get(
    "/health/ready",
    response_model=DBHealthStatus,
    status_code=status.HTTP_200_OK,
)
async def readiness_check(
    pool: Annotated[AsyncConnectionPool, Depends(get_db_pool)],
) -> DBHealthStatus:
    """Readiness probe verifying PostgreSQL connectivity, pgvector, and schema."""
    health_status = await check_db_health(pool)
    if not health_status.healthy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=health_status.model_dump(),
        )
    return health_status
