from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

MediaType = Literal["movie", "tv", "both"]
SortBy = Literal["popularity.desc", "vote_average.desc", "release_date.desc"]
RecommendMode = Literal["ai", "keyword"]


class RecommendRequest(BaseModel):
    mood_text: str = ""
    media_type_override: Optional[MediaType] = None
    selected_provider_ids: list[int] = Field(default_factory=list)
    mode: RecommendMode = "keyword"

    @field_validator("mood_text")
    @classmethod
    def strip_mood_text(cls, v: str) -> str:
        return v.strip()


class ParsedFilters(BaseModel):
    media_type: MediaType
    movie_genre_ids: list[int] = Field(default_factory=list)
    tv_genre_ids: list[int] = Field(default_factory=list)
    exclude_movie_genre_ids: list[int] = Field(default_factory=list)
    exclude_tv_genre_ids: list[int] = Field(default_factory=list)
    sort_by: SortBy = "popularity.desc"
    release_year_gte: Optional[int] = None
    release_year_lte: Optional[int] = None


class ProviderInfo(BaseModel):
    provider_id: int
    name: str
    logo_url: Optional[str] = None


class MovieResult(BaseModel):
    id: int
    title: str
    media_type: Literal["movie", "tv"]
    overview: str
    poster_url: Optional[str] = None
    providers: list[ProviderInfo] = Field(default_factory=list)


class RecommendResponse(BaseModel):
    results: list[MovieResult]
    used_filters: ParsedFilters
    used_mode: RecommendMode
