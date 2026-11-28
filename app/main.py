from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status

from app.db.pool import check_db_health, create_pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: load models, connect to DBs, start background tasks
    print("Starting up...")
    async with create_pool() as pool:
        app.state.db_pool = pool
        yield
    # Shutdown: close connections, release resources
    print("Shutting down...")


app = FastAPI(title="Codebase Oracle", lifespan=lifespan)


@app.get("/health/ready", status_code=status.HTTP_200_OK)
async def readiness_check(request: Request) -> dict[str, Any]:

    health_status = await check_db_health(request.app.state.db_pool)

    # Trigger a 503 if any critical service is down so load balancers pull the container
    if not health_status.healthy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=health_status.error
        )

    return health_status.model_dump()
