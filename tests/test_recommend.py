import pytest

from app.cache import AppCache
from app.models import ParsedFilters, RecommendRequest
from app.services import recommend


@pytest.fixture
def cache():
    c = AppCache()
    c.movie_genres = {35: "Comedy", 18: "Drama"}
    c.tv_genres = {35: "Comedy"}
    c.providers = {
        8: {"name": "Netflix", "logo_path": "/netflix.png"},
        15: {"name": "Hulu", "logo_path": "/hulu.png"},
    }
    return c


def make_raw_movie(tmdb_id, popularity=10.0):
    return {
        "id": tmdb_id,
        "_media_type": "movie",
        "title": f"Movie {tmdb_id}",
        "overview": "An overview",
        "poster_path": "/poster.jpg",
        "popularity": popularity,
    }


async def test_no_titles_available_on_selected_service_returns_empty_results(cache, mocker):
    """User selects a streaming service, but none of the matching titles are on it."""
    mocker.patch(
        "app.services.claude_client.parse_mood",
        return_value=ParsedFilters(
            media_type="movie", movie_genre_ids=[35], tv_genre_ids=[], sort_by="popularity.desc"
        ),
    )
    mocker.patch(
        "app.services.tmdb_client.discover",
        return_value=[make_raw_movie(1), make_raw_movie(2)],
    )
    mocker.patch(
        "app.services.tmdb_client.get_title_providers",
        return_value=[],  # not actually on the selected service
    )

    request = RecommendRequest(
        mood_text="something funny", selected_provider_ids=[8], mode="ai"
    )
    response = await recommend.get_recommendations(
        request, cache, http_client=None, anthropic_client=object()
    )

    assert response.results == []


async def test_empty_mood_text_still_returns_recommendations(cache, mocker):
    """User enters no mood/genre text -> broad defaults, not an error."""
    from app.services.claude_client import default_filters

    async def real_parse_mood(client, cache_, mood_text, media_type_override):
        assert mood_text == ""
        return default_filters(media_type_override)

    mocker.patch("app.services.claude_client.parse_mood", side_effect=real_parse_mood)
    mocker.patch(
        "app.services.tmdb_client.discover",
        return_value=[make_raw_movie(1)],
    )
    mocker.patch(
        "app.services.tmdb_client.get_title_providers",
        return_value=[{"provider_id": 8, "name": "Netflix", "logo_path": "/netflix.png"}],
    )

    request = RecommendRequest(mood_text="", selected_provider_ids=[8], mode="ai")
    response = await recommend.get_recommendations(
        request, cache, http_client=None, anthropic_client=object()
    )

    assert response.used_filters.media_type == "both"
    # media_type "both" discovers movie and tv separately; the stub returns one
    # stand-in result for each call.
    assert len(response.results) == 2


async def test_no_streaming_service_selected_assumes_all_services(cache, mocker):
    """No provider checkboxes ticked -> search/display across all services, don't filter."""
    mocker.patch(
        "app.services.claude_client.parse_mood",
        return_value=ParsedFilters(
            media_type="movie", movie_genre_ids=[], tv_genre_ids=[], sort_by="popularity.desc"
        ),
    )
    discover_mock = mocker.patch(
        "app.services.tmdb_client.discover",
        return_value=[make_raw_movie(1)],
    )
    mocker.patch(
        "app.services.tmdb_client.get_title_providers",
        return_value=[],  # no provider info known, irrelevant since none were selected
    )

    request = RecommendRequest(mood_text="anything", selected_provider_ids=[], mode="ai")
    response = await recommend.get_recommendations(
        request, cache, http_client=None, anthropic_client=object()
    )

    assert len(response.results) == 1  # not dropped, despite having no provider data
    provider_ids_arg = discover_mock.call_args[0][4]
    assert provider_ids_arg == []


async def test_rare_mood_word_flows_through_to_a_recommendation(cache, mocker):
    """An unusual mood word still produces filters that successfully reach a result."""
    mocker.patch(
        "app.services.claude_client.parse_mood",
        return_value=ParsedFilters(
            media_type="movie", movie_genre_ids=[35], tv_genre_ids=[], sort_by="popularity.desc"
        ),
    )
    mocker.patch(
        "app.services.tmdb_client.discover",
        return_value=[make_raw_movie(1)],
    )
    mocker.patch(
        "app.services.tmdb_client.get_title_providers",
        return_value=[{"provider_id": 8, "name": "Netflix", "logo_path": "/netflix.png"}],
    )

    request = RecommendRequest(
        mood_text="I'm feeling utterly ecstatic", selected_provider_ids=[], mode="ai"
    )
    response = await recommend.get_recommendations(
        request, cache, http_client=None, anthropic_client=object()
    )

    assert len(response.results) == 1
    assert response.results[0].title == "Movie 1"


async def test_keyword_mode_bypasses_claude_entirely(cache, mocker):
    """Keyword mode should never call Claude, so it works with no Anthropic key at all."""
    parse_mood = mocker.patch("app.services.claude_client.parse_mood")
    mocker.patch(
        "app.services.tmdb_client.discover",
        return_value=[make_raw_movie(1)],
    )
    mocker.patch(
        "app.services.tmdb_client.get_title_providers",
        return_value=[{"provider_id": 8, "name": "Netflix", "logo_path": "/netflix.png"}],
    )

    request = RecommendRequest(mood_text="something funny", selected_provider_ids=[], mode="keyword")
    response = await recommend.get_recommendations(
        request, cache, http_client=None, anthropic_client=None
    )

    parse_mood.assert_not_called()
    assert response.used_mode == "keyword"
    assert response.used_filters.movie_genre_ids == [35]  # "funny" -> Comedy, cached as id 35


async def test_ai_mode_falls_back_to_keyword_when_claude_not_configured(cache, mocker):
    """If the server has no Anthropic key, requesting AI mode shouldn't crash -
    it should silently use keyword mode instead."""
    parse_mood = mocker.patch("app.services.claude_client.parse_mood")
    mocker.patch(
        "app.services.tmdb_client.discover",
        return_value=[make_raw_movie(1)],
    )
    mocker.patch(
        "app.services.tmdb_client.get_title_providers",
        return_value=[{"provider_id": 8, "name": "Netflix", "logo_path": "/netflix.png"}],
    )

    request = RecommendRequest(mood_text="something funny", selected_provider_ids=[], mode="ai")
    response = await recommend.get_recommendations(
        request, cache, http_client=None, anthropic_client=None
    )

    parse_mood.assert_not_called()
    assert response.used_mode == "keyword"


async def test_exclude_genre_ids_reach_the_tmdb_discover_call(cache, mocker):
    """End-to-end check that an exclusion in the parsed filters actually reaches
    TMDB's query, not just the model object."""
    mocker.patch(
        "app.services.claude_client.parse_mood",
        return_value=ParsedFilters(
            media_type="movie",
            movie_genre_ids=[35],
            tv_genre_ids=[],
            exclude_movie_genre_ids=[27, 53],
            exclude_tv_genre_ids=[],
            sort_by="popularity.desc",
        ),
    )
    discover_mock = mocker.patch(
        "app.services.tmdb_client.discover",
        return_value=[make_raw_movie(1)],
    )
    mocker.patch(
        "app.services.tmdb_client.get_title_providers",
        return_value=[],
    )

    request = RecommendRequest(
        mood_text="funny, no violence", selected_provider_ids=[], mode="ai"
    )
    await recommend.get_recommendations(request, cache, http_client=None, anthropic_client=object())

    exclude_arg = discover_mock.call_args[0][7]
    assert exclude_arg == [27, 53]
