from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.database import get_async_session
from app.main import app
from app.routes import series_routes


client = TestClient(app)


class FakeScalarSession:
    def __init__(self, values):
        self._values = list(values)

    async def scalar(self, _stmt):
        return self._values.pop(0)


class FakeExecuteResult:
    def __init__(self, rows=None, scalar_rows=None):
        self._rows = rows or []
        self._scalar_rows = scalar_rows or []

    def all(self):
        return self._rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._scalar_rows)


class FakeExecuteSession:
    def __init__(self, result):
        self._result = result

    async def execute(self, _stmt):
        return self._result


def override_dependency(dependency, replacement):
    app.dependency_overrides[dependency] = replacement
    return lambda: app.dependency_overrides.pop(dependency, None)


def test_sitemap_static_returns_public_xml():
    response = client.get("/sitemap-static.xml")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<loc>https://www.toonranks.com/</loc>" in response.text
    assert "<loc>https://www.toonranks.com/privacy</loc>" in response.text


def test_sitemap_index_includes_static_series_and_forum_sitemaps():
    async def fake_session():
        yield FakeScalarSession(
            [
                2,
                datetime(2026, 5, 1, tzinfo=timezone.utc),
                1,
                "2026-05-02T00:00:00+00:00",
            ]
        )

    cleanup = override_dependency(get_async_session, fake_session)
    try:
        response = client.get("/sitemap.xml")
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<loc>https://www.toonranks.com/sitemap-static.xml</loc>" in response.text
    assert "<loc>https://www.toonranks.com/sitemaps/series-1.xml</loc>" in response.text
    assert "<loc>https://www.toonranks.com/sitemaps/forum-1.xml</loc>" in response.text


def test_series_sitemap_page_lists_approved_series_urls():
    async def fake_session():
        yield FakeScalarSession(
            [
                1,
            ]
        )

    rows = [
        SimpleNamespace(id=101, lastmod="2026-05-02T00:00:00+00:00"),
    ]
    session = FakeScalarSession([1])
    session.execute = FakeExecuteSession(FakeExecuteResult(rows=rows)).execute

    async def fake_series_session():
        yield session

    cleanup = override_dependency(get_async_session, fake_series_session)
    try:
        response = client.get("/sitemaps/series-1.xml")
    finally:
        cleanup()

    assert response.status_code == 200
    assert "<loc>https://www.toonranks.com/series/101</loc>" in response.text
    assert "<lastmod>2026-05-02</lastmod>" in response.text


def test_list_series_returns_approved_public_series():
    series = SimpleNamespace(
        id=1,
        title="Solo Leveling",
        genre="Action",
        type="MANHWA",
        author="Chugong",
        artist="DUBU",
        status="COMPLETE",
        vote_count=12,
        cover_url="https://cdn.example.com/solo.jpg",
        approval_status="APPROVED",
    )

    async def fake_series_db():
        yield FakeExecuteSession(FakeExecuteResult(scalar_rows=[series]))

    cleanup = override_dependency(series_routes.get_db, fake_series_db)
    try:
        response = client.get("/series/")
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 1,
            "title": "Solo Leveling",
            "genre": "Action",
            "type": "MANHWA",
            "author": "Chugong",
            "artist": "DUBU",
            "status": "COMPLETE",
            "vote_count": 12,
            "cover_url": "https://cdn.example.com/solo.jpg",
            "approval_status": "APPROVED",
            "external_source": None,
            "external_id": None,
            "external_url": None,
            "external_score": None,
            "external_popularity": None,
            "external_synced_at": None,
        }
    ]
