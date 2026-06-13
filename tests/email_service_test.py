import importlib

import app.email_service as email_service


def reload_email_service(monkeypatch):
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://www.toonranks.com")
    monkeypatch.delenv("FROM_EMAIL", raising=False)
    monkeypatch.setenv("VERIFICATION_FROM_EMAIL", "noreply@toonranks.com")
    monkeypatch.setenv("PASSWORD_RESET_FROM_EMAIL", "accounts@toonranks.com")
    monkeypatch.setenv("SUPPORT_EMAIL", "support@toonranks.com")
    monkeypatch.delenv("FROM_NAME", raising=False)
    monkeypatch.delenv("VERIFICATION_FROM_NAME", raising=False)
    monkeypatch.delenv("PASSWORD_RESET_FROM_NAME", raising=False)
    return importlib.reload(email_service)


def test_build_verification_email_uses_branded_sender_and_subject(monkeypatch):
    module = reload_email_service(monkeypatch)

    message = module._build_verification_email("reader@example.com", "test-token")

    assert message["From"] == "Toon Ranks Verification <noreply@toonranks.com>"
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
    assert "The Toon Ranks team" in body
    assert "This link expires in 1 hour." in body
    assert "mark them as Not Spam" in body
    assert "If you have questions, contact support@toonranks.com." in body
    assert "reply to this email" not in body.lower()
    assert "reply here" not in html.lower()
    # Header wordmark is split into two spans so "TOON" can use the brand blue
    # (matching the site logo); assert both parts are present.
    assert ">TOON</span>" in html
    assert ">RANKS</span>" in html
    assert "Confirm your Toon Ranks email" in html
    assert "Confirm email" in html
    assert "saved series, category ratings, and forum discussions" in html
    assert "mark it as Not Spam" in html
    assert "The Toon Ranks team" in html
    assert "Nofara LLC" in html
    assert "support@toonranks.com" in html
    assert "https://www.toonranks.com/android-chrome-192x192.png" in html
    assert "https://www.toonranks.com/verify-email?token=test-token" in html


def test_build_verification_email_defaults_to_noreply_alias(monkeypatch):
    module = reload_email_service(monkeypatch)
    monkeypatch.delenv("FROM_EMAIL", raising=False)
    monkeypatch.delenv("VERIFICATION_FROM_EMAIL", raising=False)
    module = importlib.reload(module)

    message = module._build_verification_email("reader@example.com", "test-token")

    assert message["From"] == "Toon Ranks Verification <noreply@toonranks.com>"
    assert message["Reply-To"] == "support@toonranks.com"


def test_build_password_reset_email_includes_plain_text_and_html_parts(monkeypatch):
    module = reload_email_service(monkeypatch)

    message = module._build_password_reset_email("reader@example.com", "reset-token")
    body = message.get_body(preferencelist=("plain",)).get_content()
    html = message.get_body(preferencelist=("html",)).get_content()

    assert message["From"] == "Toon Ranks Accounts <accounts@toonranks.com>"
    assert message["Reply-To"] == "support@toonranks.com"
    assert message["To"] == "reader@example.com"
    assert message["Subject"] == "Reset your Toon Ranks password"
    assert "https://www.toonranks.com/reset-password?token=reset-token" in body
    assert "This link expires in 30 minutes." in body
    assert "Reset your password" in html
    assert "Reset password" in html
    assert "This reset link expires in 30 minutes." in html
    assert "reply here" not in html.lower()
    assert "reply to this email" not in html.lower()
    assert "https://www.toonranks.com/reset-password?token=reset-token" in html
