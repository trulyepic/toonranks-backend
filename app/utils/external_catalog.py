import re
from typing import Any, Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict

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
