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
