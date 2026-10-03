from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import MAJOR_PROVIDER_IDS
from app.models import RecommendRequest, RecommendResponse
from app.services.recommend import get_recommendations
from app.services.tmdb_client import logo_url

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    cache = request.app.state.cache
    providers = [
        {"provider_id": pid, "name": cache.providers[pid]["name"], "logo_url": logo_url(cache.providers[pid]["logo_path"])}
        for pid in MAJOR_PROVIDER_IDS
        if pid in cache.providers
    ]
    claude_available = request.app.state.anthropic_client is not None
    return templates.TemplateResponse(
        "index.html", {"request": request, "providers": providers, "claude_available": claude_available}
    )


@router.post("/api/recommend", response_model=RecommendResponse)
async def recommend(payload: RecommendRequest, request: Request) -> RecommendResponse:
    return await get_recommendations(
        payload,
        request.app.state.cache,
        request.app.state.http_client,
        request.app.state.anthropic_client,
    )
