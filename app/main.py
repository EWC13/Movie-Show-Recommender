from contextlib import asynccontextmanager

import anthropic
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.cache import AppCache
from app.config import ANTHROPIC_API_KEY, CLAUDE_AVAILABLE
from app.routes import router
from app.services.tmdb_client import TMDBRateLimitError, TMDBServiceError, warm_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.cache = AppCache()
    app.state.http_client = httpx.AsyncClient(timeout=10.0)
    app.state.anthropic_client = (
        anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if CLAUDE_AVAILABLE else None
    )

    await warm_cache(app.state.cache, app.state.http_client)

    yield

    await app.state.http_client.aclose()


app = FastAPI(title="Mood-Based Movie/TV Recommender", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)


@app.exception_handler(TMDBRateLimitError)
async def handle_tmdb_rate_limit(request: Request, exc: TMDBRateLimitError) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests right now, please try again shortly."},
    )


@app.exception_handler(TMDBServiceError)
async def handle_tmdb_service_error(request: Request, exc: TMDBServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": "The movie database is temporarily unavailable, please try again."},
    )
