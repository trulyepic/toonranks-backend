import importlib

import pytest
from fastapi import HTTPException

import app.utils.email_token_utils as email_token_utils


def reload_email_token_utils(monkeypatch, secret_key="test-secret-key-with-at-least-32-characters"):
    monkeypatch.setenv("SECRET_KEY", secret_key)
    return importlib.reload(email_token_utils)


def test_generate_email_token_round_trips_email_address(monkeypatch):
    module = reload_email_token_utils(monkeypatch)

    token = module.generate_email_token("reader@example.com")

    assert module.verify_email_token(token) == "reader@example.com"


def test_verify_email_token_rejects_invalid_token(monkeypatch):
    module = reload_email_token_utils(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        module.verify_email_token("not-a-valid-token")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid or expired token"


def test_verify_email_token_rejects_token_signed_with_different_secret(monkeypatch):
    module = reload_email_token_utils(monkeypatch, "first-test-secret-with-at-least-32-characters")
    token = module.generate_email_token("reader@example.com")
    module = reload_email_token_utils(monkeypatch, "second-test-secret-with-at-least-32-characters")

    with pytest.raises(HTTPException) as exc_info:
        module.verify_email_token(token)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid or expired token"


def test_generate_password_reset_token_round_trips_payload(monkeypatch):
    module = reload_email_token_utils(monkeypatch)

    token = module.generate_password_reset_token("reader@example.com", "hash")

    assert module.verify_password_reset_token(token) == {
        "email": "reader@example.com",
        "password_hash": "hash",
    }


def test_password_reset_token_cannot_be_used_as_email_token(monkeypatch):
    module = reload_email_token_utils(monkeypatch)
    token = module.generate_password_reset_token("reader@example.com", "hash")

    with pytest.raises(HTTPException) as exc_info:
        module.verify_email_token(token)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid or expired token"


def test_email_token_cannot_be_used_as_password_reset_token(monkeypatch):
    module = reload_email_token_utils(monkeypatch)
    token = module.generate_email_token("reader@example.com")

    with pytest.raises(HTTPException) as exc_info:
        module.verify_password_reset_token(token)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid or expired token"
