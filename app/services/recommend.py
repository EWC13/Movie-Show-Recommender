import asyncio

import anthropic
import httpx

from app.cache import AppCache
from app.config import TITLE_PROVIDER_CACHE_TTL_SECONDS
from app.models import MovieResult, ParsedFilters, ProviderInfo, RecommendRequest, RecommendResponse
from app.services import claude_client, keyword_parser, tmdb_client

MAX_RESULTS = 20


async def get_recommendations(
    request: RecommendRequest,
    cache: AppCache,
    http_client: httpx.AsyncClient,
    anthropic_client: anthropic.AsyncAnthropic | None,
) -> RecommendResponse:
    use_ai = request.mode == "ai" and anthropic_client is not None
    used_mode = "ai" if use_ai else "keyword"

    if use_ai:
        filters = await claude_client.parse_mood(
            anthropic_client, cache, request.mood_text, request.media_type_override
        )
    else:
        filters = keyword_parser.parse_mood(cache, request.mood_text, request.media_type_override)

    # Empty selection means "no provider preference" -> search all providers,
    # rather than rejecting the request.
    selected_provider_ids = cache.valid_provider_ids(request.selected_provider_ids)

    raw_results = await _discover_all(http_client, filters, selected_provider_ids)
    results = await _annotate_with_providers(http_client, cache, raw_results, selected_provider_ids)

    if selected_provider_ids:
        # Discover's provider filter can still return titles only on rent/buy;
        # only keep ones actually confirmed on a selected flatrate service.
        results = [r for r in results if r.providers]

    results = results[:MAX_RESULTS]

    return RecommendResponse(results=results, used_filters=filters, used_mode=used_mode)


async def _discover_all(
    http_client: httpx.AsyncClient, filters: ParsedFilters, provider_ids: list[int]
) -> list[dict]:
    tasks = []
    if filters.media_type in ("movie", "both"):
        tasks.append(
            tmdb_client.discover(
                http_client,
                "movie",
                filters.movie_genre_ids,
                filters.sort_by,
                provider_ids,
                filters.release_year_gte,
                filters.release_year_lte,
                filters.exclude_movie_genre_ids,
            )
        )
    if filters.media_type in ("tv", "both"):
        tasks.append(
            tmdb_client.discover(
                http_client,
                "tv",
                filters.tv_genre_ids,
                filters.sort_by,
                provider_ids,
                filters.release_year_gte,
                filters.release_year_lte,
                filters.exclude_tv_genre_ids,
            )
        )

    results_lists = await asyncio.gather(*tasks)
    combined = [item for sublist in results_lists for item in sublist]
    combined.sort(key=lambda r: r.get("popularity", 0), reverse=True)
    return combined


async def _annotate_with_providers(
    http_client: httpx.AsyncClient,
    cache: AppCache,
    raw_results: list[dict],
    selected_provider_ids: list[int],
) -> list[MovieResult]:
    async def build(raw: dict) -> MovieResult:
        media_type = raw["_media_type"]
        tmdb_id = raw["id"]
        providers = await tmdb_client.get_title_providers(
            http_client, cache, media_type, tmdb_id, TITLE_PROVIDER_CACHE_TTL_SECONDS
        )
        if selected_provider_ids:
            providers = [p for p in providers if p["provider_id"] in selected_provider_ids]

        title = raw.get("title") or raw.get("name") or "Untitled"
        return MovieResult(
            id=tmdb_id,
            title=title,
            media_type=media_type,
            overview=raw.get("overview", ""),
            poster_url=tmdb_client.poster_url(raw.get("poster_path")),
            providers=[
                ProviderInfo(
                    provider_id=p["provider_id"],
                    name=p["name"],
                    logo_url=tmdb_client.logo_url(p.get("logo_path")),
                )
                for p in providers
            ],
        )

    return list(await asyncio.gather(*(build(r) for r in raw_results)))
