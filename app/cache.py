import time
from dataclasses import dataclass, field


@dataclass
class AppCache:
    """In-memory cache for TMDB reference data (genres, providers) and
    short-lived per-title provider lookups. Populated at startup; no
    external store needed at this scale.
    """

    movie_genres: dict = field(default_factory=dict)  # {id: name}
    tv_genres: dict = field(default_factory=dict)  # {id: name}
    providers: dict = field(default_factory=dict)  # {id: {"name": str, "logo_path": str | None}}
    _title_providers: dict = field(default_factory=dict)  # key -> (expiry_ts, value)

    def get_title_providers(self, key):
        entry = self._title_providers.get(key)
        if entry is None:
            return None
        expiry, value = entry
        if time.time() > expiry:
            del self._title_providers[key]
            return None
        return value

    def set_title_providers(self, key, value, ttl_seconds):
        self._title_providers[key] = (time.time() + ttl_seconds, value)

    def valid_movie_genre_ids(self, ids):
        return [i for i in ids if i in self.movie_genres]

    def valid_tv_genre_ids(self, ids):
        return [i for i in ids if i in self.tv_genres]

    def valid_provider_ids(self, ids):
        return [i for i in ids if i in self.providers]
