import re

from app.cache import AppCache
from app.models import ParsedFilters

# Maps a trigger word/phrase found in the user's free text to one or more
# TMDB genre *names* (not IDs - those differ between movie/tv and can change,
# so we match against the live cached genre names instead of hardcoding IDs).
# TMDB's TV genre names differ from movie genre names (e.g. "Action & Adventure"
# instead of "Action"), so matching is done as a case-insensitive substring
# check against whatever genre names are actually cached.
MOOD_KEYWORDS: dict[str, list[str]] = {
    "funny": ["Comedy"],
    "comedy": ["Comedy"],
    "hilarious": ["Comedy"],
    "laugh": ["Comedy"],
    "silly": ["Comedy"],
    "scary": ["Horror"],
    "horror": ["Horror"],
    "spooky": ["Horror"],
    "creepy": ["Horror", "Mystery"],
    "terrifying": ["Horror"],
    "thriller": ["Thriller"],
    "tense": ["Thriller"],
    "suspense": ["Thriller", "Mystery"],
    "suspenseful": ["Thriller", "Mystery"],
    "mystery": ["Mystery"],
    "whodunit": ["Mystery", "Crime"],
    "romantic": ["Romance"],
    "romance": ["Romance"],
    "love story": ["Romance"],
    "date night": ["Romance", "Comedy"],
    "sad": ["Drama"],
    "cry": ["Drama"],
    "emotional": ["Drama"],
    "drama": ["Drama"],
    "heartfelt": ["Drama", "Family"],
    "action": ["Action"],
    "exciting": ["Action", "Adventure"],
    "adrenaline": ["Action"],
    "adventure": ["Adventure"],
    "epic": ["Adventure", "Fantasy"],
    "sci-fi": ["Science Fiction"],
    "sci fi": ["Science Fiction"],
    "science fiction": ["Science Fiction"],
    "space": ["Science Fiction"],
    "mind-bending": ["Science Fiction", "Mystery"],
    "mind bending": ["Science Fiction", "Mystery"],
    "fantasy": ["Fantasy"],
    "magic": ["Fantasy"],
    "magical": ["Fantasy"],
    "animated": ["Animation"],
    "animation": ["Animation"],
    "cartoon": ["Animation"],
    "kids": ["Family", "Animation"],
    "family": ["Family"],
    "cozy": ["Comedy", "Family"],
    "feel good": ["Comedy", "Family"],
    "feel-good": ["Comedy", "Family"],
    "uplifting": ["Comedy", "Family"],
    "wholesome": ["Comedy", "Family"],
    "documentary": ["Documentary"],
    "true story": ["Documentary", "Drama"],
    "war": ["War"],
    "western": ["Western"],
    "cowboy": ["Western"],
    "crime": ["Crime"],
    "heist": ["Crime", "Thriller"],
    "detective": ["Crime", "Mystery"],
    "musical": ["Music"],
    "music": ["Music"],
    "history": ["History"],
    "historical": ["History"],
    "relax": ["Comedy", "Family"],
    "relaxing": ["Comedy", "Family"],
    "chill": ["Comedy", "Family"],
    "ecstatic": ["Comedy", "Music"],
    "happy": ["Comedy", "Family"],
    "excited": ["Action", "Adventure"],
    "bored": ["Action", "Comedy"],
    "gritty": ["Crime", "Thriller"],
    "dark": ["Thriller", "Mystery"],
    "violent": ["Action", "Thriller", "War", "Crime", "Horror"],
    "violence": ["Action", "Thriller", "War", "Crime", "Horror"],
    "gory": ["Horror"],
    "gore": ["Horror"],
}

# Phrases that inherently mean "exclude this", regardless of negation wording -
# e.g. "nonviolent" has no separate negation word for `_is_negated` to detect.
ALWAYS_EXCLUDE_KEYWORDS: dict[str, list[str]] = {
    "nonviolent": ["Action", "Thriller", "War", "Crime", "Horror"],
    "non-violent": ["Action", "Thriller", "War", "Crime", "Horror"],
    "kid-friendly": ["Horror"],
    "kid friendly": ["Horror"],
}

NEGATION_WORDS = ("no", "not", "non", "without", "avoid", "skip", "less", "none", "nothing")

BEST_RATED_TRIGGERS = ("best", "acclaimed", "top rated", "top-rated", "greatest", "highly rated")
RECENT_TRIGGERS = ("new", "recent", "latest", "just released")
GENERIC_OLD_TRIGGERS = ("classic", "old movie", "old movies", "old show", "old shows", "oldies")

# "1980s" / "1990s" etc.
_FOUR_DIGIT_DECADE = re.compile(r"\b(19|20)(\d0)s\b")
# "80s" / "90's" etc. - assumed to mean 19_0s, since that's what "old movies from
# the 80s" means colloquially (vs. a literal, rare "2080s" reading).
_TWO_DIGIT_DECADE = re.compile(r"\b(\d0)'?s\b")


def _contains_phrase(text: str, phrase: str) -> bool:
    """Whole-word/phrase match, so e.g. 'tense' doesn't false-positive match
    inside 'intense', or 'war' inside 'warm'."""
    return re.search(r"\b" + re.escape(phrase) + r"\b", text) is not None


def _is_negated(text: str, match_start: int) -> bool:
    """Checks the few words right before a keyword match for a negation cue,
    e.g. 'no violence', 'without romance', 'not too scary', "isn't too intense"."""
    preceding_words = re.findall(r"[a-z']+", text[:match_start])[-4:]
    return any(word in NEGATION_WORDS or word.endswith("n't") for word in preceding_words)


def _find_concepts(text: str) -> tuple[set[str], set[str]]:
    include: set[str] = set()
    exclude: set[str] = set()

    for keyword, concepts in MOOD_KEYWORDS.items():
        pattern = r"\b" + re.escape(keyword) + r"\b"
        for match in re.finditer(pattern, text):
            if _is_negated(text, match.start()):
                exclude.update(concepts)
            else:
                include.update(concepts)

    for keyword, concepts in ALWAYS_EXCLUDE_KEYWORDS.items():
        if _contains_phrase(text, keyword):
            exclude.update(concepts)

    # An explicit exclusion wins over an accidental simultaneous inclusion
    # (e.g. "funny but not violent" shouldn't exclude Comedy).
    include -= exclude
    return include, exclude


def _matching_genre_ids(concepts: set[str], genre_dict: dict[int, str]) -> list[int]:
    if not concepts:
        return []
    matched = [
        genre_id
        for genre_id, name in genre_dict.items()
        if any(concept.lower() in name.lower() for concept in concepts)
    ]
    return sorted(set(matched))


def _extract_year_range(text: str) -> tuple[int | None, int | None]:
    match = _FOUR_DIGIT_DECADE.search(text)
    if match:
        start = int(match.group(1) + match.group(2))
        return start, start + 9

    match = _TWO_DIGIT_DECADE.search(text)
    if match:
        start = 1900 + int(match.group(1))
        return start, start + 9

    if any(_contains_phrase(text, trigger) for trigger in GENERIC_OLD_TRIGGERS):
        return None, 1999

    return None, None


def parse_mood(cache: AppCache, mood_text: str, media_type_override: str | None) -> ParsedFilters:
    text = mood_text.lower()

    include_concepts, exclude_concepts = _find_concepts(text)

    movie_genre_ids = _matching_genre_ids(include_concepts, cache.movie_genres)
    tv_genre_ids = _matching_genre_ids(include_concepts, cache.tv_genres)
    exclude_movie_genre_ids = _matching_genre_ids(exclude_concepts, cache.movie_genres)
    exclude_tv_genre_ids = _matching_genre_ids(exclude_concepts, cache.tv_genres)

    sort_by = "popularity.desc"
    if any(_contains_phrase(text, trigger) for trigger in BEST_RATED_TRIGGERS):
        sort_by = "vote_average.desc"
    elif any(_contains_phrase(text, trigger) for trigger in RECENT_TRIGGERS):
        sort_by = "release_date.desc"

    release_year_gte, release_year_lte = _extract_year_range(text)

    return ParsedFilters(
        media_type=media_type_override or "both",
        movie_genre_ids=movie_genre_ids,
        tv_genre_ids=tv_genre_ids,
        exclude_movie_genre_ids=exclude_movie_genre_ids,
        exclude_tv_genre_ids=exclude_tv_genre_ids,
        sort_by=sort_by,
        release_year_gte=release_year_gte,
        release_year_lte=release_year_lte,
    )
