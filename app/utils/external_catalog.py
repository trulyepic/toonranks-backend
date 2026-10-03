import re
from difflib import SequenceMatcher
from typing import Any, Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.series_schemas import SeriesStatusEnum, SeriesTypeEnum


ExternalSource = Literal["ANILIST"]
AniListSort = Literal[
    "POPULARITY_DESC",
    "TRENDING_DESC",
    "SCORE_DESC",
    "START_DATE_DESC",
]

ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"


class ExternalTitleCandidate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    source: ExternalSource
    external_id: str
    external_url: str
    title: str
    type: SeriesTypeEnum
    genre: str
    synopsis: str = ""
    cover_url: str = ""
    detail_cover_url: str = ""
    author: str = ""
    artist: str = ""
    status: Optional[SeriesStatusEnum] = None
    country_of_origin: Optional[str] = None
    popularity: Optional[int] = None
    average_score: Optional[int] = None
    title_aliases: list[str] = Field(default_factory=list)


_ANILIST_SEARCH_QUERY = """
query ($search: String!, $page: Int!, $perPage: Int!) {
  Page(page: $page, perPage: $perPage) {
    media(search: $search, type: MANGA, sort: SEARCH_MATCH) {
      id
      idMal
      siteUrl
      title {
        english
        romaji
        native
      }
      synonyms
      status
      description(asHtml: false)
      countryOfOrigin
      genres
      popularity
      averageScore
      coverImage {
        extraLarge
        large
      }
      bannerImage
      staff(perPage: 10, sort: RELEVANCE) {
        edges {
          role
          node {
            name {
              full
            }
          }
        }
      }
    }
  }
}
"""

_ANILIST_DISCOVER_QUERY = """
query (
  $countryOfOrigin: CountryCode!,
  $page: Int!,
  $perPage: Int!,
  $sort: [MediaSort],
  $genres: [String]
) {
  Page(page: $page, perPage: $perPage) {
    media(
      type: MANGA,
      countryOfOrigin: $countryOfOrigin,
      genre_in: $genres,
      sort: $sort
    ) {
      id
      idMal
      siteUrl
      title {
        english
        romaji
        native
      }
      synonyms
      status
      description(asHtml: false)
      countryOfOrigin
      genres
      popularity
      averageScore
      coverImage {
        extraLarge
        large
      }
      bannerImage
      staff(perPage: 10, sort: RELEVANCE) {
        edges {
          role
          node {
            name {
              full
            }
          }
        }
      }
    }
  }
}
"""


def _clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("~!", "").replace("!~", "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _title(media: dict[str, Any]) -> str:
    title = media.get("title") or {}
    return (
        (title.get("english") or "").strip()
        or (title.get("romaji") or "").strip()
        or (title.get("native") or "").strip()
        or f"AniList #{media.get('id')}"
    )


def _title_aliases(media: dict[str, Any]) -> list[str]:
    title = media.get("title") or {}
    aliases: list[str] = []
    for value in [
        title.get("english"),
        title.get("romaji"),
        title.get("native"),
        *(media.get("synonyms") or []),
    ]:
        alias = str(value or "").strip()
        if alias and alias not in aliases:
            aliases.append(alias)
    return aliases


def normalize_title_for_match(value: str) -> str:
    normalized = (
        value.casefold()
        .replace("’", "'")
        .replace("`", "'")
        .replace("&", " and ")
    )
    normalized = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def exact_title_values_for_match(value: str) -> set[str]:
    values = {normalize_title_for_match(value)}
    for grouped_value in re.findall(r"\(([^)]*)\)|\[([^]]*)\]", value):
        grouped_text = next((part for part in grouped_value if part), "")
        values.add(normalize_title_for_match(grouped_text))
    for separator in ["/", "|"]:
        for part in value.split(separator):
            values.add(normalize_title_for_match(part))
    return {title for title in values if title}


def title_tokens_for_match(value: str) -> set[str]:
    stop_words = {"a", "an", "and", "of", "or", "the", "to"}
    return {
        token
        for token in normalize_title_for_match(value).split()
        if token and token not in stop_words
    }


def titles_match(candidate_title: str, existing_title: str) -> bool:
    candidate = normalize_title_for_match(candidate_title)
    existing = normalize_title_for_match(existing_title)
    if not candidate or not existing:
        return False
    if candidate == existing:
        return True

    shorter, longer = sorted([candidate, existing], key=len)
    if len(shorter) >= 10 and longer.startswith(f"{shorter} "):
        return True

    candidate_tokens = title_tokens_for_match(candidate)
    existing_tokens = title_tokens_for_match(existing)
    if candidate_tokens and existing_tokens:
        overlap = candidate_tokens & existing_tokens
        smaller_size = min(len(candidate_tokens), len(existing_tokens))
        if smaller_size >= 2 and len(overlap) / smaller_size >= 0.75:
            return True

    compact_candidate = candidate.replace(" ", "")
    compact_existing = existing.replace(" ", "")
    if min(len(compact_candidate), len(compact_existing)) >= 12:
        return SequenceMatcher(None, compact_candidate, compact_existing).ratio() >= 0.88

    return False


def titles_match_exactly(candidate_title: str, existing_title: str) -> bool:
    candidate_titles = exact_title_values_for_match(candidate_title)
    existing_titles = exact_title_values_for_match(existing_title)
    return bool(candidate_titles and existing_titles and candidate_titles & existing_titles)


def requires_primary_title_match(value: str) -> bool:
    normalized_values = exact_title_values_for_match(value)
    return any(len(title.split()) <= 1 for title in normalized_values)


def candidate_title_values(candidate: ExternalTitleCandidate) -> list[str]:
    titles = [candidate.title, *candidate.title_aliases]
    unique_titles: list[str] = []
    seen: set[str] = set()
    for title in titles:
        normalized = normalize_title_for_match(title)
        if normalized and normalized not in seen:
            unique_titles.append(title)
            seen.add(normalized)
    return unique_titles


def _type_from_country(country: Optional[str]) -> Optional[SeriesTypeEnum]:
    country = (country or "").upper()
    if country == "JP":
        return SeriesTypeEnum.MANGA
    if country == "KR":
        return SeriesTypeEnum.MANHWA
    if country in {"CN", "TW", "HK"}:
        return SeriesTypeEnum.MANHUA
    return None


def _country_from_type(series_type: SeriesTypeEnum) -> str:
    if series_type == SeriesTypeEnum.MANGA:
        return "JP"
    if series_type == SeriesTypeEnum.MANHWA:
        return "KR"
    return "CN"


def _status_from_anilist(status: Optional[str]) -> Optional[SeriesStatusEnum]:
    status = (status or "").upper()
    if status == "RELEASING":
        return SeriesStatusEnum.ONGOING
    if status == "FINISHED":
        return SeriesStatusEnum.COMPLETE
    if status == "HIATUS":
        return SeriesStatusEnum.HIATUS
    if status in {"CANCELLED", "NOT_YET_RELEASED"}:
        return SeriesStatusEnum.UNKNOWN
    return None


def _staff_names(media: dict[str, Any], needles: set[str]) -> str:
    edges = (((media.get("staff") or {}).get("edges")) or [])
    names: list[str] = []
    for edge in edges:
        role = str(edge.get("role") or "").lower()
        if needles and not any(needle in role for needle in needles):
            continue
        name = (((edge.get("node") or {}).get("name") or {}).get("full") or "").strip()
        if name and name not in names:
            names.append(name)
    return ", ".join(names[:3])


def normalize_anilist_media(media: dict[str, Any]) -> Optional[ExternalTitleCandidate]:
    series_type = _type_from_country(media.get("countryOfOrigin"))
    if not series_type:
        return None

    cover = media.get("coverImage") or {}
    genres = [str(genre).strip() for genre in media.get("genres") or [] if str(genre).strip()]
    author = _staff_names(media, {"story", "original", "creator", "author"})
    artist = _staff_names(media, {"art", "artist", "illustration"})

    return ExternalTitleCandidate(
        source="ANILIST",
        external_id=str(media.get("id")),
        external_url=media.get("siteUrl") or f"https://anilist.co/manga/{media.get('id')}",
        title=_title(media),
        type=series_type,
        genre=", ".join(genres),
        synopsis=_clean_text(media.get("description")),
        cover_url=cover.get("large") or cover.get("extraLarge") or "",
        detail_cover_url=media.get("bannerImage") or cover.get("extraLarge") or cover.get("large") or "",
        author=author,
        artist=artist,
        status=_status_from_anilist(media.get("status")),
        country_of_origin=media.get("countryOfOrigin"),
        popularity=media.get("popularity"),
        average_score=media.get("averageScore"),
        title_aliases=_title_aliases(media),
    )


async def search_anilist_titles(
    query: str,
    *,
    page: int = 1,
    per_page: int = 12,
    series_type: Optional[SeriesTypeEnum] = None,
) -> list[ExternalTitleCandidate]:
    payload = {
        "query": _ANILIST_SEARCH_QUERY,
        "variables": {"search": query, "page": page, "perPage": per_page},
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ToonRanks external catalog import",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(ANILIST_GRAPHQL_URL, json=payload, headers=headers)
        response.raise_for_status()

    data = response.json()
    if data.get("errors"):
        message = data["errors"][0].get("message") or "AniList search failed"
        raise httpx.HTTPStatusError(message, request=response.request, response=response)

    media_rows = (((data.get("data") or {}).get("Page") or {}).get("media")) or []
    candidates = [normalize_anilist_media(row) for row in media_rows]
    filtered = [candidate for candidate in candidates if candidate is not None]
    if series_type:
        filtered = [candidate for candidate in filtered if candidate.type == series_type]
    return filtered


async def find_anilist_match_for_title(
    title: str,
    series_type: SeriesTypeEnum,
) -> Optional[ExternalTitleCandidate]:
    title = title.strip()
    if not title:
        return None

    candidates = await search_anilist_titles(
        title,
        page=1,
        per_page=8,
        series_type=series_type,
    )
    for candidate in candidates:
        if requires_primary_title_match(title):
            if titles_match_exactly(candidate.title, title):
                return candidate
            continue

        if any(
            titles_match_exactly(candidate_title, title)
            for candidate_title in candidate_title_values(candidate)
        ):
            return candidate
    return None


async def discover_anilist_titles(
    *,
    series_type: SeriesTypeEnum,
    sort: AniListSort = "POPULARITY_DESC",
    page: int = 1,
    per_page: int = 25,
    genre: Optional[str] = None,
) -> list[ExternalTitleCandidate]:
    variables = {
        "countryOfOrigin": _country_from_type(series_type),
        "page": page,
        "perPage": per_page,
        "sort": [sort],
        "genres": [genre.strip()] if genre and genre.strip() else None,
    }
    payload = {"query": _ANILIST_DISCOVER_QUERY, "variables": variables}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ToonRanks external catalog import",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(ANILIST_GRAPHQL_URL, json=payload, headers=headers)
        response.raise_for_status()

    data = response.json()
    if data.get("errors"):
        message = data["errors"][0].get("message") or "AniList discovery failed"
        raise httpx.HTTPStatusError(message, request=response.request, response=response)

    media_rows = (((data.get("data") or {}).get("Page") or {}).get("media")) or []
    candidates = [normalize_anilist_media(row) for row in media_rows]
    return [
        candidate
        for candidate in candidates
        if candidate is not None and candidate.type == series_type
    ]
