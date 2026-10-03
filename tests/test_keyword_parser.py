import pytest

from app.cache import AppCache
from app.services import keyword_parser


@pytest.fixture
def cache():
    c = AppCache()
    c.movie_genres = {
        35: "Comedy",
        27: "Horror",
        10751: "Family",
        53: "Thriller",
        10752: "War",
        28: "Action",
        80: "Crime",
        10749: "Romance",
    }
    c.tv_genres = {35: "Comedy", 10759: "Action & Adventure"}
    return c


def test_known_keyword_maps_to_cached_genre_id(cache):
    filters = keyword_parser.parse_mood(cache, "something funny tonight", media_type_override=None)

    assert filters.movie_genre_ids == [35]
    assert filters.tv_genre_ids == [35]
    assert filters.media_type == "both"


def test_concept_matches_tv_genre_by_substring(cache):
    """'action' should match TV's 'Action & Adventure' even though the name differs from movie's 'Action'."""
    filters = keyword_parser.parse_mood(cache, "something action packed", media_type_override=None)

    assert filters.tv_genre_ids == [10759]


def test_empty_mood_text_returns_broad_defaults(cache):
    filters = keyword_parser.parse_mood(cache, "", media_type_override=None)

    assert filters.movie_genre_ids == []
    assert filters.tv_genre_ids == []
    assert filters.media_type == "both"
    assert filters.sort_by == "popularity.desc"


def test_unmatched_text_returns_empty_genre_lists_not_an_error(cache):
    filters = keyword_parser.parse_mood(cache, "asdkjfhaskjdfh", media_type_override=None)

    assert filters.movie_genre_ids == []
    assert filters.tv_genre_ids == []


def test_media_type_override_is_respected(cache):
    filters = keyword_parser.parse_mood(cache, "something funny", media_type_override="tv")

    assert filters.media_type == "tv"


def test_best_rated_phrase_sorts_by_vote_average(cache):
    filters = keyword_parser.parse_mood(cache, "the best horror movies", media_type_override=None)

    assert filters.sort_by == "vote_average.desc"
    assert filters.movie_genre_ids == [27]


def test_recent_phrase_sorts_by_release_date(cache):
    filters = keyword_parser.parse_mood(cache, "something new and scary", media_type_override=None)

    assert filters.sort_by == "release_date.desc"


def test_two_digit_decade_extracted_as_year_range(cache):
    filters = keyword_parser.parse_mood(
        cache, "I want old movies from the 80s, like an 80s western", media_type_override=None
    )

    assert filters.release_year_gte == 1980
    assert filters.release_year_lte == 1989


def test_four_digit_decade_extracted_as_year_range(cache):
    filters = keyword_parser.parse_mood(cache, "something from the 1990s", media_type_override=None)

    assert filters.release_year_gte == 1990
    assert filters.release_year_lte == 1999


def test_generic_old_without_decade_caps_at_1999(cache):
    filters = keyword_parser.parse_mood(cache, "a classic comedy", media_type_override=None)

    assert filters.release_year_gte is None
    assert filters.release_year_lte == 1999


def test_no_era_mentioned_leaves_year_range_unset(cache):
    filters = keyword_parser.parse_mood(cache, "something funny", media_type_override=None)

    assert filters.release_year_gte is None
    assert filters.release_year_lte is None


def test_intense_does_not_false_positive_match_tense(cache):
    """'tense' is a trigger for Thriller, but it must not match as a substring of 'intense'."""
    filters = keyword_parser.parse_mood(
        cache, "isn't too intense or violent", media_type_override=None
    )

    assert filters.movie_genre_ids == []


def test_warm_does_not_false_positive_match_war(cache):
    filters = keyword_parser.parse_mood(cache, "something warm and cozy", media_type_override=None)

    assert 10752 not in filters.movie_genre_ids  # War


def test_tense_alone_still_matches_thriller(cache):
    """Confirms the word-boundary fix didn't just disable the keyword entirely."""
    filters = keyword_parser.parse_mood(cache, "a tense thriller", media_type_override=None)

    assert 53 in filters.movie_genre_ids  # Thriller


def test_no_violence_excludes_violent_genres(cache):
    filters = keyword_parser.parse_mood(cache, "something fun with no violence", media_type_override=None)

    assert set(filters.exclude_movie_genre_ids) >= {27, 53, 10752, 28, 80}  # Horror/Thriller/War/Action/Crime
    assert 27 not in filters.movie_genre_ids
    assert 53 not in filters.movie_genre_ids


def test_no_romance_excludes_romance_genre(cache):
    filters = keyword_parser.parse_mood(cache, "a fun movie, no romance please", media_type_override=None)

    assert 10749 in filters.exclude_movie_genre_ids  # Romance
    assert 10749 not in filters.movie_genre_ids


def test_contraction_negation_isnt_too_violent(cache):
    """"isn't" must be recognized as a negation, not just the word 'not'."""
    filters = keyword_parser.parse_mood(
        cache, "something that isn't too violent", media_type_override=None
    )

    assert 27 in filters.exclude_movie_genre_ids  # Horror
    assert 27 not in filters.movie_genre_ids


def test_nonviolent_is_recognized_without_needing_separate_negation_word(cache):
    filters = keyword_parser.parse_mood(cache, "a nonviolent family movie", media_type_override=None)

    assert 27 in filters.exclude_movie_genre_ids  # Horror
    assert 10751 in filters.movie_genre_ids  # Family still included


def test_positive_mention_is_not_accidentally_excluded(cache):
    """A plain positive mention shouldn't end up in both lists or get excluded."""
    filters = keyword_parser.parse_mood(cache, "a funny movie", media_type_override=None)

    assert 35 in filters.movie_genre_ids  # Comedy
    assert 35 not in filters.exclude_movie_genre_ids


def test_combined_include_and_exclude_in_one_request(cache):
    """The exact kind of request that was reported broken: positive genre +
    multiple exclusions in the same sentence."""
    filters = keyword_parser.parse_mood(
        cache,
        "something for my grandma, funny, but no violence and no romance",
        media_type_override=None,
    )

    assert 35 in filters.movie_genre_ids  # Comedy included
    assert 10749 in filters.exclude_movie_genre_ids  # Romance excluded
    assert 27 in filters.exclude_movie_genre_ids  # Horror excluded (violence bucket)
    # nothing should appear in both lists at once
    assert not (set(filters.movie_genre_ids) & set(filters.exclude_movie_genre_ids))
