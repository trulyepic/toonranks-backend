import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import escape
from dotenv import load_dotenv

load_dotenv()

SITE_ORIGIN = os.getenv("PUBLIC_ORIGIN", "https://www.toonranks.com").rstrip("/")
FROM_NAME = os.getenv("FROM_NAME", "Toon Ranks Support")
LOGO_URL = os.getenv(
    "EMAIL_LOGO_URL",
    f"{SITE_ORIGIN}/android-chrome-192x192.png",
)


def _smtp_port() -> int:
    return int(os.getenv("SMTP_PORT", 587))


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required to send verification email")
    return value


def _message_id_domain(from_email: str) -> str:
    if "@" not in from_email:
        return "toonranks.com"
    return from_email.rsplit("@", 1)[1]


def _build_verification_email(to_email: str, token: str) -> EmailMessage:
    from_email = _required_env("FROM_EMAIL")

    verify_url = f"{SITE_ORIGIN}/verify-email?token={token}"
    subject = "Verify your Toon Ranks email address"
    escaped_verify_url = escape(verify_url, quote=True)
    escaped_logo_url = escape(LOGO_URL, quote=True)

    text = f"""Hi there,

Welcome to Toon Ranks. Verify your email address to finish creating your account:

{verify_url}

This verification link expires in 1 hour. If you did not create a Toon Ranks account,
you can safely ignore this email.

Thanks,
Toon Ranks Support
"""

    html = f"""\
<!doctype html>
<html>
  <body style="margin:0;background:#f6f8fb;font-family:Arial,Helvetica,sans-serif;color:#111827;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f8fb;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;">
            <tr>
              <td style="padding:28px 32px 16px;text-align:center;">
                <img src="{escaped_logo_url}" width="72" height="72" alt="Toon Ranks" style="display:inline-block;border-radius:16px;">
                <h1 style="margin:18px 0 8px;font-size:24px;line-height:32px;color:#111827;">Verify your email address</h1>
                <p style="margin:0;color:#4b5563;font-size:15px;line-height:24px;">Welcome to Toon Ranks. Confirm this email to finish creating your account.</p>
              </td>
            </tr>
            <tr>
              <td style="padding:12px 32px 28px;text-align:center;">
                <a href="{escaped_verify_url}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;font-weight:700;font-size:16px;line-height:20px;padding:14px 22px;border-radius:8px;">Verify email</a>
                <p style="margin:22px 0 0;color:#6b7280;font-size:13px;line-height:20px;">This verification link expires in 1 hour.</p>
                <p style="margin:14px 0 0;color:#6b7280;font-size:13px;line-height:20px;">If the button does not work, copy and paste this URL into your browser:</p>
                <p style="margin:8px 0 0;word-break:break-all;font-size:13px;line-height:20px;">
                  <a href="{escaped_verify_url}" style="color:#2563eb;">{escaped_verify_url}</a>
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 32px;background:#f9fafb;color:#6b7280;font-size:12px;line-height:18px;text-align:center;">
                You received this email because someone created a Toon Ranks account with this address. If that was not you, no action is needed.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    msg = EmailMessage()
    msg["From"] = formataddr((FROM_NAME, from_email))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = from_email
    msg["Message-ID"] = make_msgid(domain=_message_id_domain(from_email))
    msg["X-Auto-Response-Suppress"] = "All"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send_verification_email(to_email: str, token: str):
    smtp_host = _required_env("SMTP_HOST")
    smtp_username = _required_env("SMTP_USERNAME")
    smtp_password = _required_env("SMTP_PASSWORD")
    from_email = _required_env("FROM_EMAIL")
    msg = _build_verification_email(to_email, token)

    try:
        with smtplib.SMTP(smtp_host, _smtp_port()) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg, from_addr=from_email, to_addrs=[to_email])
    except Exception as e:
        print("SMTP send failed:", e)
        raise
