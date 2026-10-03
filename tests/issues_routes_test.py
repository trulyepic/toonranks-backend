from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.models.issue import IssueStatus, IssueType
from app.routes import issues_routes


client = TestClient(app)
NOW = datetime(2026, 5, 16, tzinfo=timezone.utc)


class FakeScalarResult:
    def __init__(self, *, rows=None, first=None):
        self._rows = rows or []
        self._first = first

    def all(self):
        return self._rows

    def first(self):
        return self._first


class FakeExecuteResult:
    def __init__(self, *, rows=None, first=None):
        self._rows = rows or []
        self._first = first

    def scalars(self):
        return FakeScalarResult(rows=self._rows, first=self._first)


class FakeIssueSession:
    def __init__(self, results=None):
        self._results = list(results or [])
        self.added = []
        self.deleted = []
        self.committed = False
        self.refreshed = []

    async def execute(self, _stmt):
        return self._results.pop(0)

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.committed = True

    async def refresh(self, item):
        self.refreshed.append(item)
        if getattr(item, "id", None) is None:
            item.id = 1
        if getattr(item, "status", None) is None:
            item.status = IssueStatus.OPEN
        if getattr(item, "created_at", None) is None:
            item.created_at = NOW
        if getattr(item, "updated_at", None) is None:
            item.updated_at = NOW

    async def delete(self, item):
        self.deleted.append(item)


def issue_object(**overrides):
    values = {
        "id": 1,
        "type": IssueType.BUG,
        "title": "Broken vote button",
        "description": "The vote button does not respond.",
        "page_url": "https://www.toonranks.com/series/1",
        "email": "reader@example.com",
        "screenshot_url": None,
        "user_id": None,
        "user_agent": "pytest-agent",
        "status": IssueStatus.OPEN,
        "admin_notes": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def override_issues_db(session):
    async def fake_get_db():
        yield session

    app.dependency_overrides[issues_routes.get_db] = fake_get_db
    return lambda: app.dependency_overrides.pop(issues_routes.get_db, None)


def override_issues_admin():
    async def fake_require_admin():
        return SimpleNamespace(id=99, role="ADMIN")

    app.dependency_overrides[issues_routes.require_admin] = fake_require_admin
    return lambda: app.dependency_overrides.pop(issues_routes.require_admin, None)


def test_extract_s3_key_returns_path_without_leading_slash():
    assert (
        issues_routes._extract_s3_key(
            "https://cdn.example.com/issues/screenshots/report.png"
        )
        == "issues/screenshots/report.png"
    )
    assert issues_routes._extract_s3_key("https://cdn.example.com/") is None


def test_report_issue_creates_anonymous_issue_with_trimmed_fields():
    session = FakeIssueSession()
    cleanup = override_issues_db(session)

    try:
        response = client.post(
            "/issues/report",
            data={
                "type": "BUG",
                "title": "  Broken vote button  ",
                "description": "  The vote button does not respond.  ",
                "page_url": "  https://www.toonranks.com/series/1  ",
                "email": "reader@example.com",
            },
            headers={"user-agent": "pytest-agent"},
        )
    finally:
        cleanup()

    assert response.status_code == 201
    assert response.json()["title"] == "Broken vote button"
    assert response.json()["description"] == "The vote button does not respond."
    assert response.json()["status"] == "OPEN"
    assert session.committed is True
    assert len(session.added) == 1
    assert session.added[0].type == IssueType.BUG
    assert session.added[0].user_id is None
    assert session.added[0].user_agent == "pytest-agent"


def test_report_issue_rejects_invalid_issue_type():
    session = FakeIssueSession()
    cleanup = override_issues_db(session)

    try:
        response = client.post(
            "/issues/report",
            data={
                "type": "NOT_REAL",
                "title": "Bad type",
                "description": "This should fail.",
            },
        )
    finally:
        cleanup()

    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid issue type"
    assert session.added == []


def test_list_issues_returns_matching_issues():
    issue = issue_object(title="Searchable report")
    session = FakeIssueSession([FakeExecuteResult(rows=[issue])])
    cleanup_db = override_issues_db(session)
    cleanup_admin = override_issues_admin()

    try:
        response = client.get("/issues?q=searchable&type=BUG&status=OPEN")
    finally:
        cleanup_admin()
        cleanup_db()

    assert response.status_code == 200
    assert response.json()[0]["title"] == "Searchable report"
    assert response.json()[0]["type"] == "BUG"
    assert response.json()[0]["status"] == "OPEN"


def test_update_issue_status_updates_admin_fields():
    issue = issue_object()
    session = FakeIssueSession([FakeExecuteResult(first=issue)])
    cleanup_db = override_issues_db(session)
    cleanup_admin = override_issues_admin()

    try:
        response = client.patch(
            "/issues/1/status",
            json={"status": "FIXED", "admin_notes": "Resolved in production."},
        )
    finally:
        cleanup_admin()
        cleanup_db()

    assert response.status_code == 200
    assert response.json()["status"] == "FIXED"
    assert response.json()["admin_notes"] == "Resolved in production."
    assert issue.status == IssueStatus.FIXED
    assert issue.admin_notes == "Resolved in production."
    assert session.committed is True


def test_delete_issue_removes_screenshot_from_s3(monkeypatch):
    deleted_keys = []
    issue = issue_object(
        screenshot_url="https://cdn.example.com/issues/screenshots/report.png"
    )
    session = FakeIssueSession([FakeExecuteResult(first=issue)])
    cleanup_db = override_issues_db(session)
    cleanup_admin = override_issues_admin()
    monkeypatch.setattr(issues_routes, "delete_from_s3", deleted_keys.append)

    try:
        response = client.delete("/issues/1")
    finally:
        cleanup_admin()
        cleanup_db()

    assert response.status_code == 204
    assert deleted_keys == ["issues/screenshots/report.png"]
    assert session.deleted == [issue]
    assert session.committed is True
