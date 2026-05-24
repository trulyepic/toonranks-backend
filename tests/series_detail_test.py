from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.routes import series_detail

client = TestClient(app)


# ---------------------------------------------------------------------------
# Minimal fake async session tailored to /me/votes query pattern:
#   execute() call 1 → count (scalar_one)
#   execute() call 2 → distinct series_ids (rows of tuples)
#   get(Series, sid)  → series object from get_results dict
#   execute() call 3+ → UserVote rows for each series (scalars().all())
# ---------------------------------------------------------------------------

class FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeExecuteResult:
    def __init__(self, *, rows=None, scalar_one=None):
        self._rows = rows or []
        self._scalar_one = scalar_one

    def scalar_one(self):
        return self._scalar_one

    def all(self):
        return self._rows

    def scalars(self):
        return FakeScalarResult(self._rows)


class FakeSeriesDetailSession:
    def __init__(self, *, results=None, get_results=None):
        self._results = list(results or [])
        self._get_results = dict(get_results or {})

    async def execute(self, _stmt):
        return self._results.pop(0)

    async def get(self, model, key):
        return self._get_results.get((model, key))


def override_series_detail_dependencies(session, *, user=None):
    current_user = user or SimpleNamespace(id=10, username="reader", role="GENERAL")

    async def fake_get_db():
        yield session

    async def fake_current_user():
        return current_user

    app.dependency_overrides[series_detail.get_async_session] = fake_get_db
    app.dependency_overrides[series_detail.get_current_user] = fake_current_user

    def cleanup():
        app.dependency_overrides.pop(series_detail.get_async_session, None)
        app.dependency_overrides.pop(series_detail.get_current_user, None)

    return cleanup


def series_object(**overrides):
    from app.models.series_model import Series
    values = {
        "id": 1,
        "title": "Solo Leveling",
        "cover_url": "https://cdn.example.com/solo.jpg",
        "type": SimpleNamespace(value="MANHWA"),
        "status": SimpleNamespace(value="COMPLETE"),
        "approval_status": "APPROVED",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def vote_object(**overrides):
    values = {
        "id": 1,
        "user_id": 10,
        "series_id": 1,
        "category": "Story",
        "score": 9,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_get_my_series_votes_returns_voted_series():
    from app.models.series_model import Series

    series = series_object()
    vote1 = vote_object(category="Story", score=9)
    vote2 = vote_object(id=2, category="Art", score=8)
    user = SimpleNamespace(id=10, username="reader", role="GENERAL")

    session = FakeSeriesDetailSession(
        results=[
            FakeExecuteResult(scalar_one=1),          # count distinct series
            FakeExecuteResult(rows=[(1,)]),            # paginated series_ids
            FakeExecuteResult(rows=[vote1, vote2]),    # UserVote rows for series 1
        ],
        get_results={
            (Series, 1): series,
        },
    )
    cleanup = override_series_detail_dependencies(session, user=user)

    try:
        response = client.get("/series-details/me/votes")
    finally:
        cleanup()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["has_prev"] is False
    assert body["has_next"] is False
    assert len(body["items"]) == 1

    item = body["items"][0]
    assert item["series_id"] == 1
    assert item["title"] == "Solo Leveling"
    assert item["cover_url"] == "https://cdn.example.com/solo.jpg"
    assert item["type"] == "MANHWA"
    assert item["status"] == "COMPLETE"
    assert len(item["votes"]) == 2
    assert {"category": "Story", "score": 9} in item["votes"]
    assert {"category": "Art", "score": 8} in item["votes"]


def test_get_my_series_votes_empty_state():
    user = SimpleNamespace(id=10, username="reader", role="GENERAL")
    session = FakeSeriesDetailSession(
        results=[
            FakeExecuteResult(scalar_one=0),  # count distinct series
            FakeExecuteResult(rows=[]),        # paginated series_ids (empty)
        ],
    )
    cleanup = override_series_detail_dependencies(session, user=user)

    try:
        response = client.get("/series-details/me/votes")
    finally:
        cleanup()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["total_pages"] == 1
    assert body["has_prev"] is False
    assert body["has_next"] is False


def test_get_my_series_votes_requires_auth():
    response = client.get("/series-details/me/votes")
    assert response.status_code == 401
