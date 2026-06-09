from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.models.series_model import SeriesStatus
from app.routes import series_routes

client = TestClient(app)


class FakeRankingsResult:
    """Fake result from db.execute(select(Series, SeriesDetail)...)."""

    def __init__(self, rows):
        # rows is a list of (series, detail_or_none) tuples
        self._rows = rows

    def all(self):
        return self._rows


class FakeRankingsSession:
    def __init__(self, rows):
        self._result = FakeRankingsResult(rows)

    async def execute(self, _stmt):
        return self._result


def make_series(*, id, title, genre, type="MANGA", vote_count=0, status=None):
    return SimpleNamespace(
        id=id,
        title=title,
        genre=genre,
        type=type,
        author="Author",
        artist="Artist",
        cover_url="https://cdn.example.com/cover.webp",
        vote_count=vote_count,
        status=status,
        approval_status="APPROVED",
    )


def override_rankings_db(session):
    async def fake_get_db():
        yield session

    app.dependency_overrides[series_routes.get_db] = fake_get_db
    return lambda: app.dependency_overrides.pop(series_routes.get_db, None)


def test_rankings_returns_all_series_without_genre_filter():
    rows = [
        (make_series(id=1, title="Action Title", genre="Action"), None),
        (make_series(id=2, title="Romance Title", genre="Romance"), None),
    ]
    session = FakeRankingsSession(rows)
    cleanup = override_rankings_db(session)

    try:
        response = client.get("/series/rankings")
    finally:
        cleanup()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    titles = {item["title"] for item in data}
    assert titles == {"Action Title", "Romance Title"}


def test_rankings_genre_param_is_accepted_and_filters_results():
    # Simulate the DB already having applied the ilike filter — only action series returned.
    rows = [
        (make_series(id=1, title="Dragon's Peak", genre="Action"), None),
    ]
    session = FakeRankingsSession(rows)
    cleanup = override_rankings_db(session)

    try:
        response = client.get("/series/rankings?genre=Action")
    finally:
        cleanup()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Dragon's Peak"
    assert data[0]["genre"] == "Action"


def test_rankings_genre_and_type_params_are_combined():
    rows = [
        (make_series(id=3, title="Fantasy Manhwa", genre="Fantasy", type="MANHWA"), None),
    ]
    session = FakeRankingsSession(rows)
    cleanup = override_rankings_db(session)

    try:
        response = client.get("/series/rankings?type=MANHWA&genre=Fantasy")
    finally:
        cleanup()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["type"] == "MANHWA"
    assert data[0]["genre"] == "Fantasy"


def test_rankings_status_param_is_accepted_and_filters_results():
    # Simulate the DB already having applied the status filter — only complete series returned.
    rows = [
        (
            make_series(
                id=4,
                title="Finished Tale",
                genre="Action",
                status=SeriesStatus.COMPLETE,
            ),
            None,
        ),
    ]
    session = FakeRankingsSession(rows)
    cleanup = override_rankings_db(session)

    try:
        response = client.get("/series/rankings?status=COMPLETE")
    finally:
        cleanup()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Finished Tale"
    assert data[0]["status"] == "COMPLETE"


def test_rankings_status_and_type_params_are_combined():
    rows = [
        (
            make_series(
                id=5,
                title="Ongoing Manhwa",
                genre="Fantasy",
                type="MANHWA",
                status=SeriesStatus.ONGOING,
            ),
            None,
        ),
    ]
    session = FakeRankingsSession(rows)
    cleanup = override_rankings_db(session)

    try:
        response = client.get("/series/rankings?type=MANHWA&status=ONGOING")
    finally:
        cleanup()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["type"] == "MANHWA"
    assert data[0]["status"] == "ONGOING"


def test_rankings_genre_filter_returns_empty_list_when_no_match():
    # DB returns nothing — no series matched the genre ilike filter.
    session = FakeRankingsSession([])
    cleanup = override_rankings_db(session)

    try:
        response = client.get("/series/rankings?genre=NonExistentGenre")
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.json() == []


def test_rankings_response_includes_required_fields():
    rows = [
        (make_series(id=10, title="Full Fields", genre="Action, Fantasy", vote_count=42), None),
    ]
    session = FakeRankingsSession(rows)
    cleanup = override_rankings_db(session)

    try:
        response = client.get("/series/rankings")
    finally:
        cleanup()

    assert response.status_code == 200
    item = response.json()[0]
    assert item["id"] == 10
    assert item["title"] == "Full Fields"
    assert item["genre"] == "Action, Fantasy"
    assert item["vote_count"] == 42
    assert "final_score" in item
    assert "rank" in item


# ── /series/search: results must keep their TRUE rank, not a re-ranked position ──


def make_detail(score):
    """Detail whose every category averages to `score`, so final_score == score."""
    return SimpleNamespace(
        story_total=score, story_count=1,
        characters_total=score, characters_count=1,
        worldbuilding_total=score, worldbuilding_count=1,
        art_total=score, art_count=1,
        drama_or_fight_total=score, drama_or_fight_count=1,
    )


class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeResult:
    def __init__(self, rows=None, scalar_rows=None):
        self._rows = rows or []
        self._scalar_rows = scalar_rows or []

    def all(self):
        return self._rows

    def scalars(self):
        return FakeScalars(self._scalar_rows)


class FakeQueuedSession:
    """Returns queued results in order — one per execute() call.

    The search endpoint executes twice: first the full ranking
    (read via .all() of (series, detail) tuples), then the search matches
    (read via .scalars().all()).
    """

    def __init__(self, results):
        self._results = list(results)
        self._i = 0

    async def execute(self, _stmt):
        result = self._results[self._i]
        self._i += 1
        return result


def test_search_results_keep_true_global_rank():
    # Full ranking: scores 9,8,7,6 -> global ranks 1,2,3,4
    full_rows = [
        (make_series(id=1, title="Alpha", genre="Action"), make_detail(9)),
        (make_series(id=2, title="Bravo", genre="Action"), make_detail(8)),
        (make_series(id=3, title="Charlie Knight", genre="Action"), make_detail(7)),
        (make_series(id=4, title="Delta Knight", genre="Action"), make_detail(6)),
    ]
    # Search for "knight" matches only the two lower-ranked series.
    search_matches = [
        make_series(id=3, title="Charlie Knight", genre="Action"),
        make_series(id=4, title="Delta Knight", genre="Action"),
    ]
    session = FakeQueuedSession([
        FakeResult(rows=full_rows),
        FakeResult(scalar_rows=search_matches),
    ])
    cleanup = override_rankings_db(session)

    try:
        response = client.get("/series/search?query=knight")
    finally:
        cleanup()

    assert response.status_code == 200
    data = response.json()
    ranks = {item["title"]: item["rank"] for item in data}
    # Must reflect their position in the FULL ranking (3 and 4),
    # NOT a re-ranked 1 and 2 among the matches.
    assert ranks == {"Charlie Knight": 3, "Delta Knight": 4}


def test_search_with_type_scopes_rank_within_type():
    # Full ranking already scoped to MANHWA: scores 9,8 -> within-type ranks 1,2
    full_rows = [
        (make_series(id=11, title="Top Manhwa", genre="Action", type="MANHWA"), make_detail(9)),
        (make_series(id=12, title="Second Manhwa", genre="Action", type="MANHWA"), make_detail(8)),
    ]
    search_matches = [
        make_series(id=12, title="Second Manhwa", genre="Action", type="MANHWA"),
    ]
    session = FakeQueuedSession([
        FakeResult(rows=full_rows),
        FakeResult(scalar_rows=search_matches),
    ])
    cleanup = override_rankings_db(session)

    try:
        response = client.get("/series/search?query=manhwa&type=MANHWA")
    finally:
        cleanup()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Second Manhwa"
    assert data[0]["rank"] == 2  # its rank within MANHWA, not 1


# ── /series/rankings: `sort` controls display order, rank stays score-based ──


def _ranking_rows():
    # Scores: Zebra=9 (#1), Alpha=7 (#2), Mango=0 (unranked)
    return [
        (make_series(id=1, title="Zebra", genre="Action", vote_count=5), make_detail(9)),
        (make_series(id=2, title="Alpha", genre="Action", vote_count=50), make_detail(7)),
        (make_series(id=3, title="Mango", genre="Action", vote_count=1), None),
    ]


def test_rankings_default_sort_is_by_score():
    session = FakeRankingsSession(_ranking_rows())
    cleanup = override_rankings_db(session)
    try:
        response = client.get("/series/rankings")
    finally:
        cleanup()

    assert response.status_code == 200
    data = response.json()
    assert [d["title"] for d in data] == ["Zebra", "Alpha", "Mango"]
    assert [d["rank"] for d in data] == [1, 2, None]


def test_rankings_sort_by_votes_keeps_score_rank():
    session = FakeRankingsSession(_ranking_rows())
    cleanup = override_rankings_db(session)
    try:
        response = client.get("/series/rankings?sort=votes")
    finally:
        cleanup()

    assert response.status_code == 200
    data = response.json()
    # Display order by votes desc: Alpha(50), Zebra(5), Mango(1)
    assert [d["title"] for d in data] == ["Alpha", "Zebra", "Mango"]
    # Rank still reflects score: Alpha #2, Zebra #1, Mango None
    assert {d["title"]: d["rank"] for d in data} == {
        "Alpha": 2,
        "Zebra": 1,
        "Mango": None,
    }


def test_rankings_sort_by_newest_orders_by_id_desc():
    session = FakeRankingsSession(_ranking_rows())
    cleanup = override_rankings_db(session)
    try:
        response = client.get("/series/rankings?sort=newest")
    finally:
        cleanup()

    assert response.status_code == 200
    data = response.json()
    assert [d["title"] for d in data] == ["Mango", "Alpha", "Zebra"]


def test_rankings_sort_by_title_orders_alphabetically():
    session = FakeRankingsSession(_ranking_rows())
    cleanup = override_rankings_db(session)
    try:
        response = client.get("/series/rankings?sort=title")
    finally:
        cleanup()

    assert response.status_code == 200
    data = response.json()
    assert [d["title"] for d in data] == ["Alpha", "Mango", "Zebra"]


# ── /series/rankings: genre/status are display filters, they don't reset rank ──


def test_rankings_genre_filter_preserves_global_rank():
    # Global ranks by score: Top=9 (#1), Mid=8 (#2), Low=7 (#3)
    rows = [
        (make_series(id=1, title="Top", genre="Action"), make_detail(9)),
        (make_series(id=2, title="Mid", genre="Romance"), make_detail(8)),
        (make_series(id=3, title="Low", genre="Action"), make_detail(7)),
    ]
    session = FakeRankingsSession(rows)
    cleanup = override_rankings_db(session)
    try:
        response = client.get("/series/rankings?genre=Action")
    finally:
        cleanup()

    assert response.status_code == 200
    data = response.json()
    # Only Action titles show, but each keeps its GLOBAL rank (1 and 3, not 1 and 2).
    assert {d["title"]: d["rank"] for d in data} == {"Top": 1, "Low": 3}


def test_rankings_status_filter_preserves_global_rank():
    rows = [
        (
            make_series(id=1, title="Top", genre="Action", status=SeriesStatus.ONGOING),
            make_detail(9),
        ),
        (
            make_series(id=2, title="Mid", genre="Action", status=SeriesStatus.COMPLETE),
            make_detail(8),
        ),
        (
            make_series(id=3, title="Low", genre="Action", status=SeriesStatus.ONGOING),
            make_detail(7),
        ),
    ]
    session = FakeRankingsSession(rows)
    cleanup = override_rankings_db(session)
    try:
        response = client.get("/series/rankings?status=ONGOING")
    finally:
        cleanup()

    assert response.status_code == 200
    data = response.json()
    assert {d["title"]: d["rank"] for d in data} == {"Top": 1, "Low": 3}
