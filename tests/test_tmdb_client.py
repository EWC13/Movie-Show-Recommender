import httpx
import respx

from app.cache import AppCache
from app.config import TMDB_BASE_URL
from app.services import tmdb_client


@respx.mock
async def test_discover_includes_provider_filter_when_providers_selected():
    route = respx.get(f"{TMDB_BASE_URL}/discover/movie").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": 1, "title": "A", "popularity": 5, "overview": "", "poster_path": None}
                ]
            },
        )
    )

    async with httpx.AsyncClient() as client:
        results = await tmdb_client.discover(
            client, "movie", genre_ids=[35], sort_by="popularity.desc", provider_ids=[8, 15]
        )

    assert len(results) == 1
    assert results[0]["_media_type"] == "movie"

    params = dict(httpx.QueryParams(route.calls.last.request.url.query))
    assert params["with_genres"] == "35"
    assert params["with_watch_providers"] == "8|15"
    assert params["with_watch_monetization_types"] == "flatrate"
    assert params["watch_region"] == "US"


@respx.mock
async def test_discover_joins_multiple_genres_with_or_not_and():
    """TMDB treats a comma in with_genres as AND (must match every genre at
    once); we want OR ('match any of these'), which TMDB spells with a pipe.
    Getting this wrong silently starves results whenever a mood maps to more
    than ~2 genres, since almost nothing is tagged with all of them."""
    route = respx.get(f"{TMDB_BASE_URL}/discover/movie").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    async with httpx.AsyncClient() as client:
        await tmdb_client.discover(
            client, "movie", genre_ids=[35, 18, 10751, 14, 99], sort_by="popularity.desc", provider_ids=[]
        )

    params = dict(httpx.QueryParams(route.calls.last.request.url.query))
    assert params["with_genres"] == "35|18|10751|14|99"


@respx.mock
async def test_discover_applies_decade_filter_for_movies():
    route = respx.get(f"{TMDB_BASE_URL}/discover/movie").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    async with httpx.AsyncClient() as client:
        await tmdb_client.discover(
            client,
            "movie",
            genre_ids=[37],
            sort_by="popularity.desc",
            provider_ids=[],
            release_year_gte=1980,
            release_year_lte=1989,
        )

    params = dict(httpx.QueryParams(route.calls.last.request.url.query))
    assert params["primary_release_date.gte"] == "1980-01-01"
    assert params["primary_release_date.lte"] == "1989-12-31"


@respx.mock
async def test_discover_applies_decade_filter_using_first_air_date_for_tv():
    route = respx.get(f"{TMDB_BASE_URL}/discover/tv").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    async with httpx.AsyncClient() as client:
        await tmdb_client.discover(
            client,
            "tv",
            genre_ids=[],
            sort_by="popularity.desc",
            provider_ids=[],
            release_year_gte=1990,
            release_year_lte=1999,
        )

    params = dict(httpx.QueryParams(route.calls.last.request.url.query))
    assert params["first_air_date.gte"] == "1990-01-01"
    assert params["first_air_date.lte"] == "1999-12-31"


@respx.mock
async def test_discover_includes_without_genres_when_exclusions_given():
    route = respx.get(f"{TMDB_BASE_URL}/discover/movie").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    async with httpx.AsyncClient() as client:
        await tmdb_client.discover(
            client,
            "movie",
            genre_ids=[35],
            sort_by="popularity.desc",
            provider_ids=[],
            exclude_genre_ids=[27, 53],
        )

    params = dict(httpx.QueryParams(route.calls.last.request.url.query))
    assert params["with_genres"] == "35"
    assert params["without_genres"] == "27,53"


@respx.mock
async def test_discover_omits_without_genres_when_no_exclusions_given():
    route = respx.get(f"{TMDB_BASE_URL}/discover/movie").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    async with httpx.AsyncClient() as client:
        await tmdb_client.discover(
            client, "movie", genre_ids=[], sort_by="popularity.desc", provider_ids=[]
        )

    params = dict(httpx.QueryParams(route.calls.last.request.url.query))
    assert "without_genres" not in params


@respx.mock
async def test_discover_omits_date_filter_when_no_year_range_given():
    route = respx.get(f"{TMDB_BASE_URL}/discover/movie").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    async with httpx.AsyncClient() as client:
        await tmdb_client.discover(
            client, "movie", genre_ids=[], sort_by="popularity.desc", provider_ids=[]
        )

    params = dict(httpx.QueryParams(route.calls.last.request.url.query))
    assert "primary_release_date.gte" not in params
    assert "primary_release_date.lte" not in params


@respx.mock
async def test_discover_omits_provider_filter_when_no_providers_selected():
    """No streaming service selected -> search everywhere, don't restrict by provider."""
    route = respx.get(f"{TMDB_BASE_URL}/discover/tv").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    async with httpx.AsyncClient() as client:
        results = await tmdb_client.discover(
            client, "tv", genre_ids=[], sort_by="popularity.desc", provider_ids=[]
        )

    assert results == []
    params = dict(httpx.QueryParams(route.calls.last.request.url.query))
    assert "with_watch_providers" not in params
    assert "with_watch_monetization_types" not in params
    assert "with_genres" not in params


@respx.mock
async def test_warm_cache_populates_genres_and_providers():
    respx.get(f"{TMDB_BASE_URL}/genre/movie/list").mock(
        return_value=httpx.Response(200, json={"genres": [{"id": 35, "name": "Comedy"}]})
    )
    respx.get(f"{TMDB_BASE_URL}/genre/tv/list").mock(
        return_value=httpx.Response(200, json={"genres": [{"id": 35, "name": "Comedy"}]})
    )
    respx.get(f"{TMDB_BASE_URL}/watch/providers/movie").mock(
        return_value=httpx.Response(
            200, json={"results": [{"provider_id": 8, "provider_name": "Netflix", "logo_path": "/n.png"}]}
        )
    )
    respx.get(f"{TMDB_BASE_URL}/watch/providers/tv").mock(
        return_value=httpx.Response(
            200, json={"results": [{"provider_id": 15, "provider_name": "Hulu", "logo_path": "/h.png"}]}
        )
    )

    cache = AppCache()
    async with httpx.AsyncClient() as client:
        await tmdb_client.warm_cache(cache, client)

    assert cache.movie_genres == {35: "Comedy"}
    assert cache.tv_genres == {35: "Comedy"}
    assert cache.providers[8]["name"] == "Netflix"
    assert cache.providers[15]["name"] == "Hulu"


@respx.mock
async def test_get_title_providers_returns_only_flatrate_in_region():
    respx.get(f"{TMDB_BASE_URL}/movie/42/watch/providers").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": {
                    "US": {
                        "flatrate": [
                            {"provider_id": 8, "provider_name": "Netflix", "logo_path": "/n.png"}
                        ],
                        "rent": [{"provider_id": 2, "provider_name": "Apple TV", "logo_path": "/a.png"}],
                    }
                }
            },
        )
    )

    cache = AppCache()
    async with httpx.AsyncClient() as client:
        providers = await tmdb_client.get_title_providers(client, cache, "movie", 42, ttl_seconds=60)

    assert providers == [{"provider_id": 8, "name": "Netflix", "logo_path": "/n.png"}]
