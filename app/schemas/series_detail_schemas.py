from pydantic import BaseModel
from typing import Optional, Dict, List

class SeriesDetailCreate(BaseModel):
    series_id: int
    synopsis: str

class SeriesDetailOut(BaseModel):
    id: int
    series_id: int
    synopsis: str
    series_cover_url: str
    title: Optional[str] = None
    genre: Optional[str] = None
    type: Optional[str] = None
    cover_url: Optional[str] = None
    approval_status: Optional[str] = None
    submitted_by_id: Optional[int] = None

    author: Optional[str] = None
    artist: Optional[str] = None

    story_total: int = 0
    story_count: int = 0
    characters_total: int = 0
    characters_count: int = 0
    worldbuilding_total: int = 0
    worldbuilding_count: int = 0
    art_total: int = 0
    art_count: int = 0
    drama_or_fight_total: int = 0
    drama_or_fight_count: int = 0

    vote_scores: Optional[Dict[str, int]] = {}
    vote_counts: Optional[Dict[str, int]] = {}

    model_config = {
        "from_attributes": True
    }


class CategoryVoteOut(BaseModel):
    category: str
    score: int


class MySeriesVoteOut(BaseModel):
    series_id: int
    title: Optional[str] = None
    cover_url: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    votes: List[CategoryVoteOut] = []


class MySeriesVotesPageOut(BaseModel):
    items: List[MySeriesVoteOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_prev: bool
    has_next: bool
