from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.models.forum_model import ForumPost, ForumReaction, ForumSeriesRef, ForumThread
from app.models.user_model import User
from app.routes import forum_routes


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
    def __init__(self, *, rows=None, first=None, scalar_one=None):
        self._rows = rows or []
        self._first = first
        self._scalar_one = scalar_one

    def all(self):
        return self._rows

    def scalars(self):
        return FakeScalarResult(rows=self._rows, first=self._first)

    def scalar_one(self):
        return self._scalar_one


class FakeForumSession:
    def __init__(self, *, results=None, get_results=None):
        self._results = list(results or [])
        self._get_results = dict(get_results or {})
        self.added = []
        self.deleted = []
        self.committed = False
        self.flushed = False
        self.refreshed = []

    async def execute(self, _stmt):
        return self._results.pop(0)

    async def get(self, model, key):
        return self._get_results.get((model, key))

    def add(self, item):
        self.added.append(item)

    async def delete(self, item):
        self.deleted.append(item)

    async def flush(self):
        self.flushed = True
        for index, item in enumerate(self.added, start=1):
            if getattr(item, "id", None) is None:
                item.id = index
            self._fill_timestamps(item)

    async def commit(self):
        self.committed = True

    async def refresh(self, item):
        self.refreshed.append(item)
        self._fill_timestamps(item)
        if getattr(item, "id", None) is None:
            item.id = 1

    def _fill_timestamps(self, item):
        if hasattr(item, "created_at"):
            item.created_at = NOW
        if hasattr(item, "updated_at"):
            item.updated_at = NOW
        if hasattr(item, "last_post_at"):
            item.last_post_at = NOW
        if hasattr(item, "post_count") and item.post_count is None:
            item.post_count = 0
        if hasattr(item, "locked") and item.locked is None:
            item.locked = False
        if hasattr(item, "latest_first") and item.latest_first is None:
            item.latest_first = False
        if hasattr(item, "heart_count") and item.heart_count is None:
            item.heart_count = 0
        if hasattr(item, "upvote_count") and item.upvote_count is None:
            item.upvote_count = 0
        if hasattr(item, "downvote_count") and item.downvote_count is None:
            item.downvote_count = 0


def thread_object(**overrides):
    values = {
        "id": 1,
        "title": "Favorite fights",
        "author_id": 10,
        "created_at": NOW,
        "updated_at": NOW,
        "post_count": 1,
        "last_post_at": NOW,
        "locked": False,
        "latest_first": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def post_object(**overrides):
    values = {
        "id": 5,
        "thread_id": 1,
        "author_id": 10,
        "parent_id": None,
        "content_markdown": "Great chapter.",
        "created_at": NOW,
        "updated_at": NOW,
        "heart_count": 0,
        "upvote_count": 0,
        "downvote_count": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def override_forum_dependencies(session, *, user=None, viewer=None):
    current_user = user or SimpleNamespace(id=10, username="reader", role="GENERAL")
    current_viewer = viewer if viewer is not None else current_user

    async def fake_get_db():
        yield session

    async def fake_current_user():
        return current_user

    async def fake_current_user_optional():
        return current_viewer

    app.dependency_overrides[forum_routes.get_async_session] = fake_get_db
    app.dependency_overrides[forum_routes.get_current_user] = fake_current_user
    app.dependency_overrides[forum_routes.get_current_user_optional] = fake_current_user_optional

    def cleanup():
        app.dependency_overrides.pop(forum_routes.get_async_session, None)
        app.dependency_overrides.pop(forum_routes.get_current_user, None)
        app.dependency_overrides.pop(forum_routes.get_current_user_optional, None)

    return cleanup


def test_create_thread_creates_thread_first_post_and_series_refs():
    session = FakeForumSession(
        results=[
            FakeExecuteResult(scalar_one=0),
            FakeExecuteResult(rows=[]),
        ],
        get_results={
            (User, 10): SimpleNamespace(
                username="reader",
                role="CONTRIBUTOR",
                avatar_url="https://cdn.example.com/avatar.webp",
                avatar_preset="emerald",
            )
        },
    )
    cleanup = override_forum_dependencies(session)

    try:
        response = client.post(
            "/forum/threads",
            json={
                "title": "Favorite fights",
                "first_post_markdown": "Which fight had the best paneling?",
                "series_ids": [101, 102],
            },
        )
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.json()["title"] == "Favorite fights"
    assert response.json()["author_username"] == "reader"
    assert response.json()["author_role"] == "CONTRIBUTOR"
    assert response.json()["author_avatar_url"] == "https://cdn.example.com/avatar.webp"
    assert response.json()["author_avatar_preset"] == "emerald"
    assert session.flushed is True
    assert session.committed is True
    assert [type(item) for item in session.added] == [
        ForumThread,
        ForumPost,
        ForumSeriesRef,
        ForumSeriesRef,
    ]
    assert session.added[1].content_markdown == "Which fight had the best paneling?"


def test_create_thread_rejects_user_thread_limit():
    session = FakeForumSession(results=[FakeExecuteResult(scalar_one=10)])
    cleanup = override_forum_dependencies(session)

    try:
        response = client.post(
            "/forum/threads",
            json={
                "title": "One more thread",
                "first_post_markdown": "This should hit the limit.",
            },
        )
    finally:
        cleanup()

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Thread limit reached (10). Delete an existing thread to create a new one."
    )
    assert session.added == []
    assert session.committed is False


def test_create_post_rejects_locked_thread_for_non_admin_user():
    session = FakeForumSession(
        get_results={(ForumThread, 1): thread_object(locked=True)}
    )
    cleanup = override_forum_dependencies(session)

    try:
        response = client.post(
            "/forum/threads/1/posts",
            json={"content_markdown": "I should not be able to reply."},
        )
    finally:
        cleanup()

    assert response.status_code == 423
    assert response.json()["detail"] == "Thread is locked"
    assert session.added == []
    assert session.committed is False


def test_create_post_returns_author_avatar_metadata():
    session = FakeForumSession(
        results=[
            FakeExecuteResult(rows=[]),
            FakeExecuteResult(scalar_one=0),
            FakeExecuteResult(scalar_one=0),
        ],
        get_results={
            (ForumThread, 1): thread_object(),
            (User, 10): SimpleNamespace(
                username="reader",
                role="ADMIN",
                avatar_url=None,
                avatar_preset="amber",
            ),
        },
    )
    cleanup = override_forum_dependencies(session)

    try:
        response = client.post(
            "/forum/threads/1/posts",
            json={"content_markdown": "This chapter worked well."},
        )
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.json()["author_username"] == "reader"
    assert response.json()["author_role"] == "ADMIN"
    assert response.json()["author_avatar_url"] is None
    assert response.json()["author_avatar_preset"] == "amber"
    assert session.flushed is True
    assert session.committed is True


def test_delete_thread_rejects_non_owner_non_admin_user():
    session = FakeForumSession(
        get_results={(ForumThread, 1): thread_object(author_id=22)}
    )
    cleanup = override_forum_dependencies(session)

    try:
        response = client.delete("/forum/threads/1")
    finally:
        cleanup()

    assert response.status_code == 403
    assert response.json()["detail"] == "Admins or the thread owner may delete this thread."
    assert session.deleted == []
    assert session.committed is False


def test_set_post_vote_adds_upvote_and_returns_counts():
    post = post_object(upvote_count=0, downvote_count=0, heart_count=0)
    session = FakeForumSession(
        results=[FakeExecuteResult(first=None)],
        get_results={(ForumPost, 5): post},
    )
    cleanup = override_forum_dependencies(session)

    try:
        response = client.post(
            "/forum/threads/1/posts/5/vote",
            json={"vote": "UPVOTE"},
        )
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.json() == {
        "viewer_vote": "UPVOTE",
        "upvote_count": 1,
        "downvote_count": 0,
    }
    assert session.committed is True
    assert len(session.added) == 1
    assert isinstance(session.added[0], ForumReaction)
    assert session.added[0].post_id == 5
    assert session.added[0].user_id == 10
    assert session.added[0].kind == "UPVOTE"
    assert post.upvote_count == 1
    assert post.downvote_count == 0
    assert post.heart_count == 1


def test_set_post_vote_switches_upvote_to_downvote():
    post = post_object(upvote_count=1, downvote_count=0, heart_count=1)
    existing = ForumReaction(post_id=5, user_id=10, kind="UPVOTE")
    session = FakeForumSession(
        results=[FakeExecuteResult(first=existing)],
        get_results={(ForumPost, 5): post},
    )
    cleanup = override_forum_dependencies(session)

    try:
        response = client.post(
            "/forum/threads/1/posts/5/vote",
            json={"vote": "DOWNVOTE"},
        )
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.json() == {
        "viewer_vote": "DOWNVOTE",
        "upvote_count": 0,
        "downvote_count": 1,
    }
    assert existing.kind == "DOWNVOTE"
    assert session.deleted == []
    assert post.upvote_count == 0
    assert post.downvote_count == 1
    assert post.heart_count == 0


def test_set_post_vote_toggles_same_vote_off():
    post = post_object(upvote_count=1, downvote_count=0, heart_count=1)
    existing = ForumReaction(post_id=5, user_id=10, kind="UPVOTE")
    session = FakeForumSession(
        results=[FakeExecuteResult(first=existing)],
        get_results={(ForumPost, 5): post},
    )
    cleanup = override_forum_dependencies(session)

    try:
        response = client.post(
            "/forum/threads/1/posts/5/vote",
            json={"vote": "UPVOTE"},
        )
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.json() == {
        "viewer_vote": None,
        "upvote_count": 0,
        "downvote_count": 0,
    }
    assert session.deleted == [existing]
    assert post.upvote_count == 0
    assert post.downvote_count == 0
    assert post.heart_count == 0


def test_toggle_heart_compatibility_maps_to_upvote():
    post = post_object(upvote_count=0, downvote_count=0, heart_count=0)
    session = FakeForumSession(
        results=[FakeExecuteResult(first=None)],
        get_results={(ForumPost, 5): post},
    )
    cleanup = override_forum_dependencies(session)

    try:
        response = client.post("/forum/threads/1/posts/5/heart")
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.json() == {"hearted": True, "count": 1}


# ------------------------------
# /me/threads tests
# ------------------------------

def test_get_my_threads_returns_users_threads():
    thread = thread_object(author_id=10)
    user = SimpleNamespace(id=10, username="reader", role="GENERAL")
    session = FakeForumSession(
        results=[
            FakeExecuteResult(scalar_one=1),          # count
            FakeExecuteResult(rows=[thread]),          # page rows
            FakeExecuteResult(rows=[]),                # _thread_to_out: series refs
        ],
        get_results={(User, 10): SimpleNamespace(
            username="reader", role="GENERAL", avatar_url=None, avatar_preset="blue"
        )},
    )
    cleanup = override_forum_dependencies(session, user=user)

    try:
        response = client.get("/forum/me/threads")
    finally:
        cleanup()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["total_pages"] == 1
    assert body["has_prev"] is False
    assert body["has_next"] is False
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "Favorite fights"


def test_get_my_threads_returns_empty_state_when_user_has_no_threads():
    user = SimpleNamespace(id=10, username="reader", role="GENERAL")
    session = FakeForumSession(
        results=[
            FakeExecuteResult(scalar_one=0),   # count
            FakeExecuteResult(rows=[]),         # page rows (empty)
        ],
    )
    cleanup = override_forum_dependencies(session, user=user)

    try:
        response = client.get("/forum/me/threads")
    finally:
        cleanup()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["total_pages"] == 1
    assert body["items"] == []


def test_get_my_threads_requires_auth():
    response = client.get("/forum/me/threads")
    assert response.status_code == 401


# ------------------------------
# /me/posts tests
# ------------------------------

def test_get_my_posts_returns_users_posts():
    post = post_object(author_id=10)
    user = SimpleNamespace(id=10, username="reader", role="GENERAL")
    session = FakeForumSession(
        results=[
            FakeExecuteResult(scalar_one=1),   # count
            FakeExecuteResult(rows=[post]),    # page rows
            FakeExecuteResult(rows=[]),        # _post_to_out: series refs
            FakeExecuteResult(scalar_one=0),   # _post_vote_bits: upvote count
            FakeExecuteResult(scalar_one=0),   # _post_vote_bits: downvote count
            FakeExecuteResult(first=None),     # _post_vote_bits: viewer vote
        ],
        get_results={(User, 10): SimpleNamespace(
            username="reader", role="GENERAL", avatar_url=None, avatar_preset="blue"
        )},
    )
    cleanup = override_forum_dependencies(session, user=user)

    try:
        response = client.get("/forum/me/posts")
    finally:
        cleanup()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["content_markdown"] == "Great chapter."


def test_get_my_posts_returns_empty_state_when_user_has_no_posts():
    user = SimpleNamespace(id=10, username="reader", role="GENERAL")
    session = FakeForumSession(
        results=[
            FakeExecuteResult(scalar_one=0),   # count
            FakeExecuteResult(rows=[]),         # page rows (empty)
        ],
    )
    cleanup = override_forum_dependencies(session, user=user)

    try:
        response = client.get("/forum/me/posts")
    finally:
        cleanup()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_get_my_posts_requires_auth():
    response = client.get("/forum/me/posts")
    assert response.status_code == 401


# ------------------------------
# /me/votes tests
# ------------------------------

def test_get_my_votes_returns_voted_posts():
    post = post_object(id=5, author_id=10)
    reaction = SimpleNamespace(id=1, post_id=5, user_id=10, kind="UPVOTE")
    user = SimpleNamespace(id=10, username="reader", role="GENERAL")
    session = FakeForumSession(
        results=[
            FakeExecuteResult(scalar_one=1),       # count reactions
            FakeExecuteResult(rows=[reaction]),    # page reactions
            FakeExecuteResult(rows=[]),            # _post_to_out: series refs
            FakeExecuteResult(scalar_one=0),       # _post_vote_bits: upvote count
            FakeExecuteResult(scalar_one=0),       # _post_vote_bits: downvote count
            FakeExecuteResult(first=None),         # _post_vote_bits: viewer vote
        ],
        get_results={
            (ForumPost, 5): post,
            (User, 10): SimpleNamespace(
                username="reader", role="GENERAL", avatar_url=None, avatar_preset="blue"
            ),
        },
    )
    cleanup = override_forum_dependencies(session, user=user)

    try:
        response = client.get("/forum/me/votes")
    finally:
        cleanup()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["content_markdown"] == "Great chapter."


def test_get_my_votes_returns_empty_state_when_user_has_no_votes():
    user = SimpleNamespace(id=10, username="reader", role="GENERAL")
    session = FakeForumSession(
        results=[
            FakeExecuteResult(scalar_one=0),   # count reactions
            FakeExecuteResult(rows=[]),         # page reactions (empty)
        ],
    )
    cleanup = override_forum_dependencies(session, user=user)

    try:
        response = client.get("/forum/me/votes")
    finally:
        cleanup()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_get_my_votes_requires_auth():
    response = client.get("/forum/me/votes")
    assert response.status_code == 401
