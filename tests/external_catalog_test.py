from types import SimpleNamespace

import pytest

from app.models.series_model import SeriesApprovalStatus, SeriesStatus
from app.routes import external_catalog_routes
from app.routes.external_catalog_routes import (
    ExternalBatchImportRequest,
    ExternalImportRequest,
    import_external_batch,
    import_external_title,
)
from app.utils.external_catalog import (
    ExternalTitleCandidate,
    normalize_anilist_media,
    requires_primary_title_match,
    titles_match_exactly,
)


def test_normalize_anilist_media_maps_country_to_toonranks_type():
    candidate = normalize_anilist_media(
        {
            "id": 151807,
            "siteUrl": "https://anilist.co/manga/151807",
            "title": {"english": "Test Manhwa", "romaji": "Romanized"},
            "status": "RELEASING",
            "description": "Line one<br>Line two",
            "countryOfOrigin": "KR",
            "genres": ["Action", "Fantasy"],
            "popularity": 1234,
            "averageScore": 82,
            "coverImage": {"large": "https://img.example.com/cover.jpg"},
            "bannerImage": "https://img.example.com/banner.jpg",
            "staff": {
                "edges": [
                    {"role": "Story", "node": {"name": {"full": "Writer"}}},
                    {"role": "Art", "node": {"name": {"full": "Artist"}}},
                ]
            },
        }
    )

    assert candidate is not None
    assert candidate.external_id == "151807"
    assert candidate.title == "Test Manhwa"
    assert candidate.type == "MANHWA"
    assert candidate.genre == "Action, Fantasy"
    assert candidate.status == "ONGOING"
    assert candidate.synopsis == "Line one\nLine two"
    assert candidate.author == "Writer"
    assert candidate.artist == "Artist"


def test_exact_title_match_accepts_aliases_and_parenthetical_titles():
    assert titles_match_exactly("That Time I Got Reincarnated as a Slime", "Tensei Shitara Slime Datta Ken (That Time I Got Reincarnated as a Slime)")
    assert titles_match_exactly("Attack on Titan", "Shingeki no Kyojin / Attack on Titan")


def test_exact_title_match_rejects_related_but_different_titles():
    assert not titles_match_exactly("Jigokuraku Bangai-hen", "Hell's Paradise: Jigokuraku")
    assert not titles_match_exactly("Life with an Ordinary Guy Who Reincarnated into a Total Fantasy Knockout", "Isekai Ojisan")


def test_short_titles_require_primary_title_match_for_enrichment():
    assert requires_primary_title_match("Real")
    assert not requires_primary_title_match("The Legend of the Northern Blade")


class FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return FakeScalarResult(self._rows)


class FakeImportSession:
    def __init__(self, *, scalars=None, execute_rows=None):
        self._scalars = list(scalars or [])
        self._execute_rows = list(execute_rows or [])
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.refreshed = []

    async def scalar(self, _stmt):
        if self._scalars:
            return self._scalars.pop(0)
        return None

    async def execute(self, _stmt):
        if self._execute_rows:
            return FakeExecuteResult(self._execute_rows.pop(0))
        return FakeExecuteResult([])

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = 42

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, item):
        self.refreshed.append(item)


def import_payload(**overrides):
    values = {
        "source": "ANILIST",
        "external_id": "151807",
        "external_url": "https://anilist.co/manga/151807",
        "title": "Imported Title",
        "type": "MANHWA",
        "genre": "Action, Fantasy",
        "synopsis": "Imported synopsis.",
        "cover_url": "https://img.example.com/cover.jpg",
        "detail_cover_url": "https://img.example.com/banner.jpg",
        "author": "Writer",
        "artist": "Artist",
        "status": "ONGOING",
    }
    values.update(overrides)
    return ExternalImportRequest(**values)


@pytest.mark.anyio
async def test_import_external_title_creates_pending_review_title():
    session = FakeImportSession(scalars=[None], execute_rows=[[]])
    admin = SimpleNamespace(id=7, username="admin")

    result = await import_external_title(import_payload(), admin_user=admin, session=session)

    assert result.imported is True
    assert result.duplicate is False
    assert result.series.id == 42
    assert result.series.approval_status == SeriesApprovalStatus.PENDING.value
    assert result.series.external_source == "ANILIST"
    assert result.series.external_id == "151807"
    assert result.series.detail_ready is True
    assert session.committed is True

    series = session.added[0]
    assert series.status == SeriesStatus.ONGOING
    assert series.submitted_by_id == admin.id
    detail = session.added[1]
    assert detail.synopsis == "Imported synopsis."
    assert detail.series_cover_url == "https://img.example.com/banner.jpg"


@pytest.mark.anyio
async def test_import_external_title_returns_existing_duplicate():
    existing = SimpleNamespace(
        id=9,
        title="Existing Title",
        genre="Action",
        type="MANHWA",
        author="Writer",
        artist="Artist",
        status=SeriesStatus.ONGOING,
        vote_count=0,
        cover_url="https://img.example.com/cover.jpg",
        approval_status=SeriesApprovalStatus.PENDING.value,
        submitted_by_id=7,
        approved_by_id=None,
        approved_at=None,
        external_source="ANILIST",
        external_id="151807",
        external_url="https://anilist.co/manga/151807",
    )
    session = FakeImportSession(scalars=[existing])
    admin = SimpleNamespace(id=7, username="admin")

    result = await import_external_title(import_payload(), admin_user=admin, session=session)

    assert result.imported is False
    assert result.duplicate is True
    assert result.series.id == existing.id
    assert session.added == []
    assert session.committed is False


@pytest.mark.anyio
async def test_import_external_title_matches_existing_title_without_source():
    existing = SimpleNamespace(
        id=9,
        title="Imported Title",
        genre="Action",
        type="MANHWA",
        author="Writer",
        artist="Artist",
        status=SeriesStatus.ONGOING,
        vote_count=12,
        cover_url="https://img.example.com/existing.jpg",
        approval_status=SeriesApprovalStatus.APPROVED.value,
        submitted_by_id=None,
        approved_by_id=1,
        approved_at="2026-01-01T00:00:00+00:00",
        external_source=None,
        external_id=None,
        external_url=None,
    )
    session = FakeImportSession(scalars=[None], execute_rows=[[existing]])
    admin = SimpleNamespace(id=7, username="admin")

    result = await import_external_title(import_payload(title=" imported title "), admin_user=admin, session=session)

    assert result.imported is False
    assert result.duplicate is True
    assert result.series.id == existing.id
    assert session.added == []
    assert session.committed is False


@pytest.mark.anyio
async def test_import_external_title_matches_existing_alias_title_without_source():
    existing = SimpleNamespace(
        id=58,
        title="Mercenary Enrollment",
        genre="Action",
        type="MANHWA",
        author="Writer",
        artist="Artist",
        status=SeriesStatus.ONGOING,
        vote_count=12,
        cover_url="https://img.example.com/existing.jpg",
        approval_status=SeriesApprovalStatus.APPROVED.value,
        submitted_by_id=None,
        approved_by_id=1,
        approved_at="2026-01-01T00:00:00+00:00",
        external_source=None,
        external_id=None,
        external_url=None,
    )
    session = FakeImportSession(scalars=[None], execute_rows=[[existing]])
    admin = SimpleNamespace(id=7, username="admin")

    result = await import_external_title(
        import_payload(
            title="Teenage Mercenary",
            title_aliases=["Teenage Mercenary", "Mercenary Enrollment"],
        ),
        admin_user=admin,
        session=session,
    )

    assert result.imported is False
    assert result.duplicate is True
    assert result.series.id == existing.id
    assert session.added == []
    assert session.committed is False


@pytest.mark.anyio
async def test_import_external_title_matches_existing_similar_title_without_source():
    existing = SimpleNamespace(
        id=125,
        title="Omniscient Reader’s Viewpoint",
        genre="Action",
        type="MANHWA",
        author="Writer",
        artist="Artist",
        status=SeriesStatus.ONGOING,
        vote_count=12,
        cover_url="https://img.example.com/existing.jpg",
        approval_status=SeriesApprovalStatus.APPROVED.value,
        submitted_by_id=None,
        approved_by_id=1,
        approved_at="2026-01-01T00:00:00+00:00",
        external_source=None,
        external_id=None,
        external_url=None,
    )
    session = FakeImportSession(scalars=[None], execute_rows=[[existing]])
    admin = SimpleNamespace(id=7, username="admin")

    result = await import_external_title(
        import_payload(title="Omniscient Reader"),
        admin_user=admin,
        session=session,
    )

    assert result.imported is False
    assert result.duplicate is True
    assert result.series.id == existing.id
    assert session.added == []
    assert session.committed is False


def candidate(**overrides):
    values = {
        "source": "ANILIST",
        "external_id": "201",
        "external_url": "https://anilist.co/manga/201",
        "title": "Batch Title",
        "type": "MANHWA",
        "genre": "Action",
        "synopsis": "Batch synopsis.",
        "cover_url": "https://img.example.com/cover.jpg",
        "detail_cover_url": "https://img.example.com/banner.jpg",
        "author": "Writer",
        "artist": "Artist",
        "status": "ONGOING",
        "country_of_origin": "KR",
        "popularity": 100,
        "average_score": 80,
    }
    values.update(overrides)
    return ExternalTitleCandidate(**values)


@pytest.mark.anyio
async def test_batch_import_creates_only_new_pending_titles(monkeypatch):
    existing = SimpleNamespace(
        id=9,
        title="Existing Title",
        genre="Action",
        type="MANHWA",
        author="Writer",
        artist="Artist",
        status=SeriesStatus.ONGOING,
        vote_count=0,
        cover_url="https://img.example.com/existing.jpg",
        approval_status=SeriesApprovalStatus.APPROVED.value,
        submitted_by_id=1,
        approved_by_id=1,
        approved_at="2026-01-01T00:00:00+00:00",
        external_source="ANILIST",
        external_id="202",
        external_url="https://anilist.co/manga/202",
    )

    async def fake_discover(**_kwargs):
        return [
            candidate(external_id="201", title="New Batch Title"),
            candidate(external_id="202", title="Existing Title"),
        ]

    monkeypatch.setattr(external_catalog_routes, "discover_anilist_titles", fake_discover)
    session = FakeImportSession(scalars=[None, existing], execute_rows=[[]])
    admin = SimpleNamespace(id=7, username="admin")

    result = await import_external_batch(
        ExternalBatchImportRequest(type="MANHWA", sort="POPULARITY_DESC"),
        admin_user=admin,
        session=session,
    )

    assert result.imported == 1
    assert result.duplicates == 1
    assert result.skipped == 0
    assert len(result.items) == 2
    assert session.committed is True

    created_series = session.added[0]
    assert created_series.title == "New Batch Title"
    assert created_series.approval_status == SeriesApprovalStatus.PENDING.value
    assert created_series.external_id == "201"

    # Existing rows are reported as duplicates and are not modified/re-added.
    assert existing.title == "Existing Title"
    assert session.added[0] is not existing


@pytest.mark.anyio
async def test_batch_import_rolls_back_when_every_candidate_is_duplicate(monkeypatch):
    existing = SimpleNamespace(
        id=9,
        title="Existing Title",
        genre="Action",
        type="MANHWA",
        author="Writer",
        artist="Artist",
        status=SeriesStatus.ONGOING,
        vote_count=0,
        cover_url="https://img.example.com/existing.jpg",
        approval_status=SeriesApprovalStatus.PENDING.value,
        submitted_by_id=1,
        approved_by_id=None,
        approved_at=None,
        external_source="ANILIST",
        external_id="202",
        external_url="https://anilist.co/manga/202",
    )

    async def fake_discover(**_kwargs):
        return [candidate(external_id="202", title="Existing Title")]

    monkeypatch.setattr(external_catalog_routes, "discover_anilist_titles", fake_discover)
    session = FakeImportSession(scalars=[existing])
    admin = SimpleNamespace(id=7, username="admin")

    result = await import_external_batch(
        ExternalBatchImportRequest(type="MANHWA", sort="POPULARITY_DESC"),
        admin_user=admin,
        session=session,
    )

    assert result.imported == 0
    assert result.duplicates == 1
    assert result.skipped == 0
    assert session.added == []
    assert session.committed is False
    assert session.rolled_back is True
