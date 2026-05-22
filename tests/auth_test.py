import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from PIL import Image

from app.models.mobile_auth_code import MobileAuthCode
from app.main import app
from app.routes import auth


client = TestClient(app)


class FakeScalarResult:
    def __init__(self, rows=None, one=None):
        self._rows = rows or []
        self._one = one

    def all(self):
        return self._rows

    def first(self):
        return self._one


class FakeExecuteResult:
    def __init__(self, rows=None, one=None):
        self._rows = rows or []
        self._one = one

    def scalars(self):
        return FakeScalarResult(rows=self._rows, one=self._one)

    def scalar_one_or_none(self):
        return self._one


class FakeAuthSession:
    def __init__(self, *, execute_result=None, get_result=None):
        self.execute_result = execute_result or FakeExecuteResult()
        self.get_result = get_result
        self.added = []
        self.committed = False
        self.flushed = False
        self.refreshed = []
        self.rolled_back = False

    async def execute(self, _stmt):
        return self.execute_result

    async def get(self, _model, _id):
        return self.get_result

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True

    async def refresh(self, item):
        self.refreshed.append(item)
        if getattr(item, "id", None) is None:
            item.id = 1

    async def rollback(self):
        self.rolled_back = True


def override_auth_db(session):
    async def fake_get_db():
        yield session

    app.dependency_overrides[auth.get_db] = fake_get_db
    return lambda: app.dependency_overrides.pop(auth.get_db, None)


def override_auth_user(user):
    async def fake_current_user():
        return user

    app.dependency_overrides[auth.get_current_user] = fake_current_user
    return lambda: app.dependency_overrides.pop(auth.get_current_user, None)


async def fake_verify_captcha(*args, **kwargs):
    return None


def make_image_bytes(*, size=(64, 48), image_format="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(32, 96, 160)).save(buffer, format=image_format)
    return buffer.getvalue()


def test_signup_creates_unverified_user_with_normalized_email(monkeypatch):
    session = FakeAuthSession()
    cleanup = override_auth_db(session)
    sent_emails = []

    monkeypatch.setattr(auth, "verify_captcha", fake_verify_captcha)
    monkeypatch.setattr(auth, "generate_email_token", lambda email: f"token-for-{email}")
    monkeypatch.setattr(
        auth,
        "send_verification_email",
        lambda email, token: sent_emails.append((email, token)),
    )

    try:
        response = client.post(
            "/auth/signup",
            json={
                "username": "  NewReader  ",
                "password": "safe-password",
                "email": "Reader@Gmail.com",
                "captcha_token": "captcha-token",
            },
        )
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.json() == {
        "message": (
            "User created successfully. Please check your inbox and Spam folder "
            "for the verification email."
        ),
        "token": "token-for-reader@gmail.com",
    }
    assert session.flushed is True
    assert session.committed is True
    assert session.rolled_back is False
    assert sent_emails == [("reader@gmail.com", "token-for-reader@gmail.com")]
    assert len(session.added) == 1
    assert session.added[0].username == "NewReader"
    assert session.added[0].email == "reader@gmail.com"
    assert session.added[0].is_verified is False
    assert auth.bcrypt.verify("safe-password", session.added[0].password)


def test_signup_rejects_existing_email(monkeypatch):
    existing = SimpleNamespace(username="OtherUser", email="reader@gmail.com")
    session = FakeAuthSession(execute_result=FakeExecuteResult(rows=[existing]))
    cleanup = override_auth_db(session)

    monkeypatch.setattr(auth, "verify_captcha", fake_verify_captcha)

    try:
        response = client.post(
            "/auth/signup",
            json={
                "username": "NewReader",
                "password": "safe-password",
                "email": "reader@gmail.com",
                "captcha_token": "captcha-token",
            },
        )
    finally:
        cleanup()

    assert response.status_code == 409
    assert response.json()["detail"] == "Email already exists"
    assert session.added == []


def test_signup_rolls_back_when_verification_email_fails(monkeypatch):
    session = FakeAuthSession()
    cleanup = override_auth_db(session)

    monkeypatch.setattr(auth, "verify_captcha", fake_verify_captcha)
    monkeypatch.setattr(auth, "generate_email_token", lambda email: "token")

    def fail_send(*args, **kwargs):
        raise RuntimeError("smtp unavailable")

    monkeypatch.setattr(auth, "send_verification_email", fail_send)

    try:
        response = client.post(
            "/auth/signup",
            json={
                "username": "NewReader",
                "password": "safe-password",
                "email": "reader@gmail.com",
                "captcha_token": "captcha-token",
            },
        )
    finally:
        cleanup()

    assert response.status_code == 500
    assert response.json()["detail"] == "Signup failed during email sending"
    assert session.rolled_back is True
    assert session.committed is False


def test_login_returns_access_token_for_verified_user(monkeypatch):
    db_user = SimpleNamespace(
        id=7,
        username="reader",
        password=auth.bcrypt.hash("safe-password"),
        is_verified=True,
        role="GENERAL",
    )
    session = FakeAuthSession(execute_result=FakeExecuteResult(one=db_user))
    cleanup = override_auth_db(session)

    monkeypatch.setattr(auth, "verify_captcha", fake_verify_captcha)
    monkeypatch.setattr(auth, "create_access_token", lambda user: f"token-for-{user.username}")

    try:
        response = client.post(
            "/auth/login",
            json={
                "username": "reader",
                "password": "safe-password",
                "captcha_token": "captcha-token",
            },
        )
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "token-for-reader",
        "user": {
            "id": 7,
            "username": "reader",
            "role": "GENERAL",
            "avatar_url": None,
            "avatar_preset": "blue",
        },
    }


def test_login_rejects_invalid_password(monkeypatch):
    db_user = SimpleNamespace(
        id=7,
        username="reader",
        password=auth.bcrypt.hash("safe-password"),
        is_verified=True,
        role="GENERAL",
    )
    session = FakeAuthSession(execute_result=FakeExecuteResult(one=db_user))
    cleanup = override_auth_db(session)

    monkeypatch.setattr(auth, "verify_captcha", fake_verify_captcha)

    try:
        response = client.post(
            "/auth/login",
            json={
                "username": "reader",
                "password": "wrong-password",
                "captcha_token": "captcha-token",
            },
        )
    finally:
        cleanup()

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_login_rejects_unverified_user(monkeypatch):
    db_user = SimpleNamespace(
        id=7,
        username="reader",
        password=auth.bcrypt.hash("safe-password"),
        is_verified=False,
        role="GENERAL",
    )
    session = FakeAuthSession(execute_result=FakeExecuteResult(one=db_user))
    cleanup = override_auth_db(session)

    monkeypatch.setattr(auth, "verify_captcha", fake_verify_captcha)

    try:
        response = client.post(
            "/auth/login",
            json={
                "username": "reader",
                "password": "safe-password",
                "captcha_token": "captcha-token",
            },
        )
    finally:
        cleanup()

    assert response.status_code == 403
    assert response.json()["detail"] == "Email not verified"


def test_forgot_password_sends_reset_email_without_revealing_account(monkeypatch):
    db_user = SimpleNamespace(
        email="reader@gmail.com",
        password="current-hash",
    )
    session = FakeAuthSession(execute_result=FakeExecuteResult(one=db_user))
    cleanup = override_auth_db(session)
    sent_emails = []

    monkeypatch.setattr(
        auth,
        "generate_password_reset_token",
        lambda email, password_hash: f"reset-token-for-{email}-{password_hash}",
    )
    monkeypatch.setattr(
        auth,
        "send_password_reset_email",
        lambda email, token: sent_emails.append((email, token)),
    )

    try:
        response = client.post(
            "/auth/forgot-password",
            json={"email": "Reader@Gmail.com"},
        )
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.json() == {"message": auth.FORGOT_PASSWORD_MESSAGE}
    assert sent_emails == [
        ("reader@gmail.com", "reset-token-for-reader@gmail.com-current-hash")
    ]
    assert session.committed is False


def test_forgot_password_returns_generic_message_for_unknown_email(monkeypatch):
    session = FakeAuthSession(execute_result=FakeExecuteResult(one=None))
    cleanup = override_auth_db(session)

    monkeypatch.setattr(
        auth,
        "send_password_reset_email",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("email sent")),
    )

    try:
        response = client.post(
            "/auth/forgot-password",
            json={"email": "missing@gmail.com"},
        )
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.json() == {"message": auth.FORGOT_PASSWORD_MESSAGE}
    assert session.committed is False


def test_reset_password_updates_password_and_invalidates_token(monkeypatch):
    db_user = SimpleNamespace(
        email="reader@gmail.com",
        password=auth.bcrypt.hash("old-password"),
    )
    old_hash = db_user.password
    session = FakeAuthSession(execute_result=FakeExecuteResult(one=db_user))
    cleanup = override_auth_db(session)

    monkeypatch.setattr(
        auth,
        "verify_password_reset_token",
        lambda token: {"email": "reader@gmail.com", "password_hash": old_hash},
    )

    try:
        response = client.post(
            "/auth/reset-password",
            json={"token": "reset-token", "password": "new-password"},
        )
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.json() == {"message": "Password reset successful. You can now log in."}
    assert session.committed is True
    assert db_user.password != old_hash
    assert auth.bcrypt.verify("new-password", db_user.password)


def test_reset_password_rejects_reused_token_after_password_changes(monkeypatch):
    db_user = SimpleNamespace(
        email="reader@gmail.com",
        password=auth.bcrypt.hash("new-password"),
    )
    session = FakeAuthSession(execute_result=FakeExecuteResult(one=db_user))
    cleanup = override_auth_db(session)

    monkeypatch.setattr(
        auth,
        "verify_password_reset_token",
        lambda token: {
            "email": "reader@gmail.com",
            "password_hash": "old-password-hash",
        },
    )

    try:
        response = client.post(
            "/auth/reset-password",
            json={"token": "reset-token", "password": "another-password"},
        )
    finally:
        cleanup()

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired token"
    assert session.committed is False


def test_reset_password_rejects_short_password(monkeypatch):
    session = FakeAuthSession()
    cleanup = override_auth_db(session)

    monkeypatch.setattr(
        auth,
        "verify_password_reset_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("token used")),
    )

    try:
        response = client.post(
            "/auth/reset-password",
            json={"token": "reset-token", "password": "short"},
        )
    finally:
        cleanup()

    assert response.status_code == 400
    assert response.json()["detail"] == "Password must be at least 8 characters"
    assert session.committed is False


def test_create_mobile_auth_code_returns_deep_link_callback():
    current_user = SimpleNamespace(id=7, username="reader", role="GENERAL")
    session = FakeAuthSession()
    cleanup_db = override_auth_db(session)
    cleanup_user = override_auth_user(current_user)

    try:
        response = client.post(
            "/auth/mobile-code",
            json={
                "redirect_uri": "toonranks://auth/callback",
                "state": "state-123",
            },
        )
    finally:
        cleanup_user()
        cleanup_db()

    assert response.status_code == 200
    body = response.json()
    assert body["expires_in"] == auth.MOBILE_AUTH_CODE_EXPIRE_SECONDS
    assert body["code"]
    assert body["redirect_url"].startswith("toonranks://auth/callback?")

    parsed = urlparse(body["redirect_url"])
    params = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "toonranks://auth/callback"
    assert params["code"] == [body["code"]]
    assert params["state"] == ["state-123"]

    assert session.committed is True
    assert len(session.added) == 1
    stored = session.added[0]
    assert isinstance(stored, MobileAuthCode)
    assert stored.user_id == 7
    assert stored.redirect_uri == "toonranks://auth/callback"
    assert stored.state == "state-123"
    assert stored.code_hash == auth.hash_mobile_auth_code(body["code"])
    assert stored.code_hash != body["code"]


def test_create_mobile_auth_code_rejects_unknown_redirect_uri():
    current_user = SimpleNamespace(id=7, username="reader", role="GENERAL")
    session = FakeAuthSession()
    cleanup_db = override_auth_db(session)
    cleanup_user = override_auth_user(current_user)

    try:
        response = client.post(
            "/auth/mobile-code",
            json={
                "redirect_uri": "https://evil.example/callback",
                "state": "state-123",
            },
        )
    finally:
        cleanup_user()
        cleanup_db()

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid mobile redirect URI"
    assert session.added == []
    assert session.committed is False


def test_exchange_mobile_auth_code_returns_token_and_marks_code_used(monkeypatch):
    auth_code = SimpleNamespace(
        user_id=7,
        code_hash=auth.hash_mobile_auth_code("mobile-code"),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        used_at=None,
    )
    db_user = SimpleNamespace(
        id=7,
        username="reader",
        role="CONTRIBUTOR",
        avatar_url="https://cdn.example.com/avatar.webp",
        avatar_preset="emerald",
    )
    session = FakeAuthSession(
        execute_result=FakeExecuteResult(one=auth_code),
        get_result=db_user,
    )
    cleanup = override_auth_db(session)
    monkeypatch.setattr(auth, "create_access_token", lambda user: f"token-for-{user.username}")

    try:
        response = client.post("/auth/mobile-token", json={"code": "mobile-code"})
    finally:
        cleanup()

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "token-for-reader",
        "user": {
            "id": 7,
            "username": "reader",
            "role": "CONTRIBUTOR",
            "avatar_url": "https://cdn.example.com/avatar.webp",
            "avatar_preset": "emerald",
        },
    }
    assert auth_code.used_at is not None
    assert session.committed is True


def test_exchange_mobile_auth_code_rejects_reused_code(monkeypatch):
    auth_code = SimpleNamespace(
        user_id=7,
        code_hash=auth.hash_mobile_auth_code("mobile-code"),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        used_at=datetime.now(timezone.utc),
    )
    session = FakeAuthSession(execute_result=FakeExecuteResult(one=auth_code))
    cleanup = override_auth_db(session)
    monkeypatch.setattr(
        auth,
        "create_access_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("token created")),
    )

    try:
        response = client.post("/auth/mobile-token", json={"code": "mobile-code"})
    finally:
        cleanup()

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired mobile auth code"
    assert session.committed is False


def test_exchange_mobile_auth_code_rejects_expired_code(monkeypatch):
    auth_code = SimpleNamespace(
        user_id=7,
        code_hash=auth.hash_mobile_auth_code("mobile-code"),
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        used_at=None,
    )
    session = FakeAuthSession(execute_result=FakeExecuteResult(one=auth_code))
    cleanup = override_auth_db(session)
    monkeypatch.setattr(
        auth,
        "create_access_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("token created")),
    )

    try:
        response = client.post("/auth/mobile-token", json={"code": "mobile-code"})
    finally:
        cleanup()

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired mobile auth code"
    assert auth_code.used_at is None
    assert session.committed is False


def test_exchange_mobile_auth_code_rejects_unknown_code():
    session = FakeAuthSession(execute_result=FakeExecuteResult(one=None))
    cleanup = override_auth_db(session)

    try:
        response = client.post("/auth/mobile-token", json={"code": "missing-code"})
    finally:
        cleanup()

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired mobile auth code"
    assert session.committed is False


def test_normalize_avatar_image_returns_square_webp():
    output = auth.normalize_avatar_image(make_image_bytes(size=(80, 40)))

    with Image.open(output) as image:
        assert image.size == (auth.AVATAR_SIZE, auth.AVATAR_SIZE)
        assert image.format == "WEBP"


def test_upload_my_avatar_normalizes_and_persists_url(monkeypatch):
    current_user = SimpleNamespace(id=7, username="reader", role="GENERAL")
    db_user = SimpleNamespace(
        id=7,
        username="reader",
        role="GENERAL",
        avatar_url=None,
        avatar_preset=None,
    )
    session = FakeAuthSession(get_result=db_user)
    cleanup_db = override_auth_db(session)
    cleanup_user = override_auth_user(current_user)
    uploaded = []

    def fake_upload(fileobj, filename, content_type, folder, subfolder):
        uploaded.append(
            {
                "bytes": fileobj.read(),
                "filename": filename,
                "content_type": content_type,
                "folder": folder,
                "subfolder": subfolder,
            }
        )
        return "https://cdn.example.com/avatars/7/avatar.webp"

    monkeypatch.setattr(auth, "upload_to_s3", fake_upload)

    try:
        response = client.post(
            "/auth/me/avatar",
            files={"file": ("avatar.png", make_image_bytes(), "image/png")},
        )
    finally:
        cleanup_user()
        cleanup_db()

    assert response.status_code == 200
    assert response.json() == {
        "id": 7,
        "username": "reader",
        "role": "GENERAL",
        "avatar_url": "https://cdn.example.com/avatars/7/avatar.webp",
        "avatar_preset": "blue",
    }
    assert session.committed is True
    assert uploaded[0]["filename"] == "avatar.webp"
    assert uploaded[0]["content_type"] == "image/webp"
    assert uploaded[0]["folder"] == "avatars"
    assert uploaded[0]["subfolder"] == "7"

    with Image.open(io.BytesIO(uploaded[0]["bytes"])) as image:
        assert image.size == (auth.AVATAR_SIZE, auth.AVATAR_SIZE)
        assert image.format == "WEBP"


def test_upload_my_avatar_rejects_unsupported_file_without_s3(monkeypatch):
    current_user = SimpleNamespace(id=7, username="reader", role="GENERAL")
    session = FakeAuthSession(get_result=current_user)
    cleanup_db = override_auth_db(session)
    cleanup_user = override_auth_user(current_user)
    monkeypatch.setattr(
        auth,
        "upload_to_s3",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("S3 called")),
    )

    try:
        response = client.post(
            "/auth/me/avatar",
            files={"file": ("avatar.txt", b"hello", "text/plain")},
        )
    finally:
        cleanup_user()
        cleanup_db()

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported avatar image type"
    assert session.committed is False


def test_select_my_avatar_preset_clears_custom_avatar():
    current_user = SimpleNamespace(id=7, username="reader", role="GENERAL")
    db_user = SimpleNamespace(
        id=7,
        username="reader",
        role="GENERAL",
        avatar_url="https://cdn.example.com/custom.webp",
        avatar_preset="blue",
    )
    session = FakeAuthSession(get_result=db_user)
    cleanup_db = override_auth_db(session)
    cleanup_user = override_auth_user(current_user)

    try:
        response = client.patch(
            "/auth/me/avatar/preset",
            json={"avatar_preset": "emerald"},
        )
    finally:
        cleanup_user()
        cleanup_db()

    assert response.status_code == 200
    assert response.json() == {
        "id": 7,
        "username": "reader",
        "role": "GENERAL",
        "avatar_url": None,
        "avatar_preset": "emerald",
    }
    assert db_user.avatar_url is None
    assert db_user.avatar_preset == "emerald"
    assert session.committed is True


def test_select_my_avatar_preset_rejects_unknown_preset():
    current_user = SimpleNamespace(id=7, username="reader", role="GENERAL")
    session = FakeAuthSession(get_result=current_user)
    cleanup_db = override_auth_db(session)
    cleanup_user = override_auth_user(current_user)

    try:
        response = client.patch(
            "/auth/me/avatar/preset",
            json={"avatar_preset": "purple"},
        )
    finally:
        cleanup_user()
        cleanup_db()

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid avatar preset"
    assert session.committed is False


def test_reset_my_avatar_clears_custom_avatar():
    current_user = SimpleNamespace(id=7, username="reader", role="GENERAL")
    db_user = SimpleNamespace(
        id=7,
        username="reader",
        role="GENERAL",
        avatar_url="https://cdn.example.com/custom.webp",
        avatar_preset=None,
    )
    session = FakeAuthSession(get_result=db_user)
    cleanup_db = override_auth_db(session)
    cleanup_user = override_auth_user(current_user)

    try:
        response = client.delete("/auth/me/avatar")
    finally:
        cleanup_user()
        cleanup_db()

    assert response.status_code == 200
    assert response.json() == {
        "id": 7,
        "username": "reader",
        "role": "GENERAL",
        "avatar_url": None,
        "avatar_preset": "blue",
    }
    assert db_user.avatar_url is None
    assert db_user.avatar_preset == "blue"
    assert session.committed is True
