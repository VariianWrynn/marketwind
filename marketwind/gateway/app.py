"""Minimal FastAPI app exposing a real-dependency health check."""

import asyncpg
import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from marketwind.config import settings

app = FastAPI(title="MarketWind")


async def _check_postgres() -> bool:
    try:
        conn = await asyncpg.connect(settings.database_url)
        try:
            return await conn.fetchval("select 1;") == 1
        finally:
            await conn.close()
    except Exception:
        return False


async def _check_redis() -> bool:
    try:
        client = redis.from_url(settings.redis_url)
        try:
            return bool(await client.ping())
        finally:
            await client.aclose()
    except Exception:
        return False


@app.get("/health")
async def health() -> JSONResponse:
    """Probe Postgres and Redis; ok only if both are reachable, else 503."""
    postgres = await _check_postgres()
    redis_ok = await _check_redis()
    ok = postgres and redis_ok
    body = {
        "status": "ok" if ok else "degraded",
        "postgres": postgres,
        "redis": redis_ok,
    }
    return JSONResponse(body, status_code=200 if ok else 503)
