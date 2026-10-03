import json
import logging

import anthropic

from app.cache import AppCache
from app.config import CLAUDE_MODEL
from app.models import ParsedFilters

logger = logging.getLogger(__name__)

VALID_SORT_BY = ("popularity.desc", "vote_average.desc", "release_date.desc")

EXTRACT_FILTERS_TOOL = {
    "name": "extract_filters",
    "description": "Extract structured movie/TV database search filters from a free-text mood or genre request.",
    "input_schema": {
        "type": "object",
        "properties": {
            "media_type": {
                "type": "string",
                "enum": ["movie", "tv", "both"],
                "description": "Whether the user wants a movie, a TV show, or is open to either.",
            },
            "movie_genre_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "TMDB movie genre IDs matching the mood, chosen only from the provided movie genre list.",
            },
            "tv_genre_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "TMDB TV genre IDs matching the mood, chosen only from the provided TV genre list.",
            },
            "exclude_movie_genre_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "TMDB movie genre IDs to actively EXCLUDE, chosen only from the provided "
                    "movie genre list. Populate this whenever the user says things like 'no "
                    "violence', 'nothing scary', 'without romance', 'avoid horror', 'not too "
                    "intense' - map the unwanted theme to the closest matching genre(s) (e.g. "
                    "'violence' -> Action, Thriller, War, Crime; 'romance' -> Romance) so those "
                    "titles are filtered out server-side, not just mentally noted. A genre must "
                    "never appear in both this list and movie_genre_ids at the same time."
                ),
            },
            "exclude_tv_genre_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "Same as exclude_movie_genre_ids, but chosen only from the provided TV "
                    "genre list."
                ),
            },
            "sort_by": {
                "type": "string",
                "enum": list(VALID_SORT_BY),
                "description": "How results should be ranked.",
            },
            "release_year_min": {
                "type": ["integer", "null"],
                "description": (
                    "Earliest release year to include, if the user mentioned a decade, "
                    "era, or year range (e.g. '80s', '1990s', 'something old'). Null if "
                    "no era was implied."
                ),
            },
            "release_year_max": {
                "type": ["integer", "null"],
                "description": (
                    "Latest release year to include, if the user mentioned a decade, era, "
                    "or year range. For a single decade like '80s', set both min and max "
                    "to span that decade (1980-1989). For 'old movies' with no specific "
                    "decade, set max to roughly 1999 and leave min null. Null if no era "
                    "was implied."
                ),
            },
        },
        "required": ["media_type", "movie_genre_ids", "tv_genre_ids", "sort_by"],
    },
}


def default_filters(media_type_override: str | None = None) -> ParsedFilters:
    return ParsedFilters(
        media_type=media_type_override or "both",
        movie_genre_ids=[],
        tv_genre_ids=[],
        exclude_movie_genre_ids=[],
        exclude_tv_genre_ids=[],
        sort_by="popularity.desc",
    )


def _build_prompt(mood_text: str, cache: AppCache) -> str:
    movie_genres = [{"id": i, "name": n} for i, n in cache.movie_genres.items()]
    tv_genres = [{"id": i, "name": n} for i, n in cache.tv_genres.items()]
    return (
        "A user wants a movie or TV show recommendation. Translate their request into "
        "search filters.\n\n"
        f"User request: {mood_text!r}\n\n"
        f"Available movie genres: {json.dumps(movie_genres)}\n"
        f"Available TV genres: {json.dumps(tv_genres)}\n\n"
        "Pick genre IDs only from the lists above. The database matches ANY of the genres "
        "you list, not all of them - so pick the smallest set of genres that precisely "
        "captures the request (usually 1-3), not a long or padded list. In particular, "
        "don't add a broad catch-all genre like Comedy or Drama just because it's loosely "
        "associated - a request for 'kids cartoons' should get Animation/Family/Kids, NOT "
        "plus a bare Comedy that will pull in unrelated wildly-popular comedy talk shows. "
        "If the request doesn't clearly imply any particular genre (e.g. it only describes "
        "a mood like 'ecstatic' or 'relaxed'), pick the 1-2 genres that best fit that feeling "
        "anyway — don't return empty lists unless truly nothing fits. Pick sort_by based on "
        "tone: vote_average.desc for requests like "
        "'best' or 'acclaimed', release_date.desc for 'new' or 'recent', otherwise "
        "popularity.desc. If the user mentions an era, decade, or year range (e.g. '80s "
        "western', 'something from the 90s', 'old movies'), set release_year_min/"
        "release_year_max to match it precisely — this is important, since otherwise "
        "results will span any era and won't match what they asked for. Pay close attention "
        "to anything the user wants to AVOID (e.g. 'no violence', 'nothing scary', 'not too "
        "intense', 'without romance') and put the corresponding genre(s) in "
        "exclude_movie_genre_ids / exclude_tv_genre_ids — this is just as important as picking "
        "the right genres to include, since otherwise the exclusion is silently ignored and "
        "the user gets exactly what they asked not to see."
    )


async def parse_mood(
    client: anthropic.AsyncAnthropic,
    cache: AppCache,
    mood_text: str,
    media_type_override: str | None,
) -> ParsedFilters:
    if not mood_text:
        return default_filters(media_type_override)

    try:
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            tools=[EXTRACT_FILTERS_TOOL],
            tool_choice={"type": "tool", "name": "extract_filters"},
            messages=[{"role": "user", "content": _build_prompt(mood_text, cache)}],
        )
    except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
        logger.warning("Claude mood parsing failed, using defaults: %s", exc)
        return default_filters(media_type_override)

    if response.stop_reason == "refusal":
        logger.warning("Claude refused to parse mood text, using defaults")
        return default_filters(media_type_override)

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        logger.warning("Claude response had no tool_use block, using defaults")
        return default_filters(media_type_override)

    raw = tool_use.input
    movie_genre_ids = cache.valid_movie_genre_ids(raw.get("movie_genre_ids", []))
    tv_genre_ids = cache.valid_tv_genre_ids(raw.get("tv_genre_ids", []))
    exclude_movie_genre_ids = cache.valid_movie_genre_ids(raw.get("exclude_movie_genre_ids", []))
    exclude_tv_genre_ids = cache.valid_tv_genre_ids(raw.get("exclude_tv_genre_ids", []))

    # An exclusion must win over an accidental simultaneous inclusion.
    movie_genre_ids = [g for g in movie_genre_ids if g not in exclude_movie_genre_ids]
    tv_genre_ids = [g for g in tv_genre_ids if g not in exclude_tv_genre_ids]

    media_type = media_type_override or raw.get("media_type", "both")
    sort_by = raw.get("sort_by", "popularity.desc")
    if sort_by not in VALID_SORT_BY:
        sort_by = "popularity.desc"

    release_year_gte, release_year_lte = _clamp_year_range(
        raw.get("release_year_min"), raw.get("release_year_max")
    )

    return ParsedFilters(
        media_type=media_type,
        movie_genre_ids=movie_genre_ids,
        tv_genre_ids=tv_genre_ids,
        exclude_movie_genre_ids=exclude_movie_genre_ids,
        exclude_tv_genre_ids=exclude_tv_genre_ids,
        sort_by=sort_by,
        release_year_gte=release_year_gte,
        release_year_lte=release_year_lte,
    )


def _clamp_year_range(
    year_min: int | None, year_max: int | None
) -> tuple[int | None, int | None]:
    """Guards against a hallucinated/nonsensical year breaking the TMDB query."""
    earliest, latest = 1888, 2035  # 1888 ~ earliest surviving motion picture

    def _sanitize(year):
        if not isinstance(year, int):
            return None
        return year if earliest <= year <= latest else None

    year_min, year_max = _sanitize(year_min), _sanitize(year_max)
    if year_min is not None and year_max is not None and year_min > year_max:
        year_min, year_max = year_max, year_min
    return year_min, year_max
