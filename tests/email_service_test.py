import importlib

import pytest

import app.email_service as email_service


def reload_email_service(monkeypatch):
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://www.toonranks.com")
    monkeypatch.setenv("FROM_EMAIL", "support@toonranks.com")
    monkeypatch.setenv("FROM_NAME", "Toon Ranks Support")
    return importlib.reload(email_service)


def test_build_verification_email_uses_branded_sender_and_subject(monkeypatch):
    module = reload_email_service(monkeypatch)

    message = module._build_verification_email("reader@example.com", "test-token")

    assert message["From"] == "Toon Ranks Support <support@toonranks.com>"
    assert message["Reply-To"] == "support@toonranks.com"
    assert message["To"] == "reader@example.com"
    assert message["Subject"] == "Verify your Toon Ranks email address"
    assert message["Message-ID"].endswith("@toonranks.com>")


def test_build_verification_email_includes_plain_text_and_html_parts(monkeypatch):
    module = reload_email_service(monkeypatch)

    message = module._build_verification_email("reader@example.com", "test-token")
    body = message.get_body(preferencelist=("plain",)).get_content()
    html = message.get_body(preferencelist=("html",)).get_content()

    assert "https://www.toonranks.com/verify-email?token=test-token" in body
    assert "This verification link expires in 1 hour." in body
    assert "Verify email" in html
    assert "https://www.toonranks.com/android-chrome-192x192.png" in html
    assert "https://www.toonranks.com/verify-email?token=test-token" in html


def test_build_verification_email_requires_from_email(monkeypatch):
    module = reload_email_service(monkeypatch)
    monkeypatch.delenv("FROM_EMAIL")

    with pytest.raises(RuntimeError) as exc_info:
        module._build_verification_email("reader@example.com", "test-token")

    assert str(exc_info.value) == "FROM_EMAIL is required to send verification email"
