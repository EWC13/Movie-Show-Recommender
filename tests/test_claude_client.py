from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.cache import AppCache
from app.services import claude_client


@pytest.fixture
def cache():
    c = AppCache()
    c.movie_genres = {35: "Comedy", 10402: "Music", 18: "Drama", 53: "Thriller", 10749: "Romance"}
    c.tv_genres = {35: "Comedy", 10749: "Romance"}
    return c


def make_tool_response(tool_input, stop_reason="tool_use"):
    tool_use_block = SimpleNamespace(type="tool_use", input=tool_input)
    return SimpleNamespace(stop_reason=stop_reason, content=[tool_use_block])


async def test_empty_mood_text_uses_defaults_without_calling_claude(cache, mocker):
    """No mood/genre entered -> fall back to broad defaults instead of calling the API."""
    client = mocker.AsyncMock()

    filters = await claude_client.parse_mood(client, cache, "", media_type_override=None)

    assert filters.media_type == "both"
    assert filters.movie_genre_ids == []
    assert filters.tv_genre_ids == []
    assert filters.sort_by == "popularity.desc"
    client.messages.create.assert_not_called()


async def test_rare_mood_word_maps_to_genres_and_clamps_hallucinated_ids(cache, mocker):
    """An unusual mood word ('ecstatic') should still produce a valid, clamped filter set."""
    client = mocker.AsyncMock()
    client.messages.create.return_value = make_tool_response(
        {
            "media_type": "movie",
            "movie_genre_ids": [35, 10402, 999999],  # 999999 isn't a real cached genre
            "tv_genre_ids": [],
            "sort_by": "popularity.desc",
        }
    )

    filters = await claude_client.parse_mood(
        client, cache, "I'm feeling utterly ecstatic today", media_type_override=None
    )

    assert filters.media_type == "movie"
    assert filters.movie_genre_ids == [35, 10402]  # hallucinated id dropped
    assert filters.tv_genre_ids == []


async def test_year_range_from_claude_is_passed_through(cache, mocker):
    client = mocker.AsyncMock()
    client.messages.create.return_value = make_tool_response(
        {
            "media_type": "movie",
            "movie_genre_ids": [],
            "tv_genre_ids": [],
            "sort_by": "popularity.desc",
            "release_year_min": 1980,
            "release_year_max": 1989,
        }
    )

    filters = await claude_client.parse_mood(
        client, cache, "an 80s western", media_type_override=None
    )

    assert filters.release_year_gte == 1980
    assert filters.release_year_lte == 1989


async def test_nonsensical_year_from_claude_is_dropped(cache, mocker):
    """Guard against a hallucinated/out-of-range year breaking the TMDB query."""
    client = mocker.AsyncMock()
    client.messages.create.return_value = make_tool_response(
        {
            "media_type": "movie",
            "movie_genre_ids": [],
            "tv_genre_ids": [],
            "sort_by": "popularity.desc",
            "release_year_min": 9999,
            "release_year_max": None,
        }
    )

    filters = await claude_client.parse_mood(client, cache, "something", media_type_override=None)

    assert filters.release_year_gte is None
    assert filters.release_year_lte is None


async def test_exclude_genre_ids_from_claude_are_passed_through(cache, mocker):
    client = mocker.AsyncMock()
    client.messages.create.return_value = make_tool_response(
        {
            "media_type": "movie",
            "movie_genre_ids": [35],
            "tv_genre_ids": [],
            "exclude_movie_genre_ids": [53, 10749],
            "exclude_tv_genre_ids": [],
            "sort_by": "popularity.desc",
        }
    )

    filters = await claude_client.parse_mood(
        client, cache, "funny, no violence or romance", media_type_override=None
    )

    assert filters.movie_genre_ids == [35]
    assert set(filters.exclude_movie_genre_ids) == {53, 10749}


async def test_claude_overlap_between_include_and_exclude_is_resolved_in_favor_of_exclude(cache, mocker):
    """If Claude contradicts itself and puts the same genre in both lists,
    the exclusion must win so a user's 'no X' is never silently dropped."""
    client = mocker.AsyncMock()
    client.messages.create.return_value = make_tool_response(
        {
            "media_type": "movie",
            "movie_genre_ids": [35, 10749],
            "tv_genre_ids": [],
            "exclude_movie_genre_ids": [10749],
            "exclude_tv_genre_ids": [],
            "sort_by": "popularity.desc",
        }
    )

    filters = await claude_client.parse_mood(client, cache, "funny, no romance", media_type_override=None)

    assert filters.movie_genre_ids == [35]
    assert 10749 not in filters.movie_genre_ids
    assert 10749 in filters.exclude_movie_genre_ids


async def test_hallucinated_exclude_genre_id_is_clamped(cache, mocker):
    client = mocker.AsyncMock()
    client.messages.create.return_value = make_tool_response(
        {
            "media_type": "movie",
            "movie_genre_ids": [],
            "tv_genre_ids": [],
            "exclude_movie_genre_ids": [999999],
            "exclude_tv_genre_ids": [],
            "sort_by": "popularity.desc",
        }
    )

    filters = await claude_client.parse_mood(client, cache, "no violence", media_type_override=None)

    assert filters.exclude_movie_genre_ids == []


async def test_media_type_override_takes_precedence_over_claude_choice(cache, mocker):
    client = mocker.AsyncMock()
    client.messages.create.return_value = make_tool_response(
        {"media_type": "movie", "movie_genre_ids": [], "tv_genre_ids": [], "sort_by": "popularity.desc"}
    )

    filters = await claude_client.parse_mood(client, cache, "something funny", media_type_override="tv")

    assert filters.media_type == "tv"


async def test_refusal_falls_back_to_defaults(cache, mocker):
    client = mocker.AsyncMock()
    client.messages.create.return_value = make_tool_response({}, stop_reason="refusal")

    filters = await claude_client.parse_mood(client, cache, "something tense", media_type_override=None)

    assert filters == claude_client.default_filters()


async def test_api_failure_falls_back_to_defaults(cache, mocker):
    client = mocker.AsyncMock()
    dummy_request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client.messages.create.side_effect = anthropic.APIConnectionError(request=dummy_request)

    filters = await claude_client.parse_mood(client, cache, "something tense", media_type_override="tv")

    assert filters.media_type == "tv"
    assert filters.movie_genre_ids == []
