import asyncio

import httpx

from app.cache import AppCache
from app.config import TMDB_API_KEY, TMDB_BASE_URL, TMDB_IMAGE_BASE_URL, WATCH_REGION


class TMDBRateLimitError(Exception):
    pass


class TMDBServiceError(Exception):
    pass


def _auth_params(extra: dict | None = None) -> dict:
    params = {"api_key": TMDB_API_KEY, "language": "en-US"}
    if extra:
        params.update(extra)
    return params


async def _get(client: httpx.AsyncClient, path: str, params: dict, retry: bool = True) -> dict:
    try:
        resp = await client.get(f"{TMDB_BASE_URL}{path}", params=params)
    except httpx.TransportError as exc:
        raise TMDBServiceError(f"TMDB request failed: {exc}") from exc

    if resp.status_code == 429:
        raise TMDBRateLimitError("TMDB rate limit exceeded")

    if resp.status_code >= 500:
        if retry:
            await asyncio.sleep(0.5)
            return await _get(client, path, params, retry=False)
        raise TMDBServiceError(f"TMDB server error: {resp.status_code}")

    resp.raise_for_status()
    return resp.json()


async def warm_cache(cache: AppCache, client: httpx.AsyncClient) -> None:
    movie_genres, tv_genres, movie_providers, tv_providers = await asyncio.gather(
        _get(client, "/genre/movie/list", _auth_params()),
        _get(client, "/genre/tv/list", _auth_params()),
        _get(client, "/watch/providers/movie", _auth_params({"watch_region": WATCH_REGION})),
        _get(client, "/watch/providers/tv", _auth_params({"watch_region": WATCH_REGION})),
    )

    cache.movie_genres = {g["id"]: g["name"] for g in movie_genres.get("genres", [])}
    cache.tv_genres = {g["id"]: g["name"] for g in tv_genres.get("genres", [])}

    providers: dict = {}
    for payload in (movie_providers, tv_providers):
        for p in payload.get("results", []):
            providers[p["provider_id"]] = {
                "name": p.get("provider_name", "Unknown"),
                "logo_path": p.get("logo_path"),
            }
    cache.providers = providers


async def discover(
    client: httpx.AsyncClient,
    media_type: str,
    genre_ids: list[int],
    sort_by: str,
    provider_ids: list[int],
    release_year_gte: int | None = None,
    release_year_lte: int | None = None,
    exclude_genre_ids: list[int] | None = None,
) -> list[dict]:
    """media_type must be 'movie' or 'tv'. Empty provider_ids means no provider filter."""
    params = _auth_params(
        {
            "sort_by": sort_by,
            "vote_count.gte": 50,
            "watch_region": WATCH_REGION,
        }
    )
    if genre_ids:
        # Pipe = OR ("match any of these genres"). TMDB treats a comma here as
        # AND (must match ALL listed genres at once), which silently starved
        # results whenever a mood mapped to more than ~2 genres.
        params["with_genres"] = "|".join(str(g) for g in genre_ids)
    if exclude_genre_ids:
        # Comma = OR for exclusion ("exclude if it has ANY of these genres"),
        # which is what we want here - this one was already correct.
        params["without_genres"] = ",".join(str(g) for g in exclude_genre_ids)
    if provider_ids:
        params["with_watch_providers"] = "|".join(str(p) for p in provider_ids)
        params["with_watch_monetization_types"] = "flatrate"

    date_field = "primary_release_date" if media_type == "movie" else "first_air_date"
    if release_year_gte:
        params[f"{date_field}.gte"] = f"{release_year_gte}-01-01"
    if release_year_lte:
        params[f"{date_field}.lte"] = f"{release_year_lte}-12-31"

    path = "/discover/movie" if media_type == "movie" else "/discover/tv"
    data = await _get(client, path, params)
    results = data.get("results", [])
    for r in results:
        r["_media_type"] = media_type
    return results


async def get_title_providers(
    client: httpx.AsyncClient,
    cache: AppCache,
    media_type: str,
    tmdb_id: int,
    ttl_seconds: int,
) -> list[dict]:
    """Returns the flatrate (subscription) providers for a title in WATCH_REGION,
    using a short-lived cache since popular titles repeat across requests."""
    cache_key = f"{media_type}:{tmdb_id}"
    cached = cache.get_title_providers(cache_key)
    if cached is not None:
        return cached

    path = f"/{media_type}/{tmdb_id}/watch/providers"
    data = await _get(client, path, _auth_params())
    region = data.get("results", {}).get(WATCH_REGION, {})
    flatrate = region.get("flatrate", [])
    providers = [
        {
            "provider_id": p["provider_id"],
            "name": p.get("provider_name", "Unknown"),
            "logo_path": p.get("logo_path"),
        }
        for p in flatrate
    ]
    cache.set_title_providers(cache_key, providers, ttl_seconds)
    return providers


def poster_url(poster_path: str | None) -> str | None:
    if not poster_path:
        return None
    return f"{TMDB_IMAGE_BASE_URL}/w342{poster_path}"


def logo_url(logo_path: str | None) -> str | None:
    if not logo_path:
        return None
    return f"{TMDB_IMAGE_BASE_URL}/w45{logo_path}"
