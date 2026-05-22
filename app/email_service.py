import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import escape
from dotenv import load_dotenv

load_dotenv()

SITE_ORIGIN = os.getenv("PUBLIC_ORIGIN", "https://www.toonranks.com").rstrip("/")
FROM_NAME = os.getenv("FROM_NAME", "Toon Ranks")
LOGO_URL = os.getenv(
    "EMAIL_LOGO_URL",
    f"{SITE_ORIGIN}/android-chrome-192x192.png",
)
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@toonranks.com")
OPERATOR_NAME = os.getenv("OPERATOR_NAME", "Nofara LLC")


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

Welcome to Toon Ranks. Verify your email address to finish creating your account.

{verify_url}

This verification link expires in 1 hour. If you have questions, reply to this email
or contact {SUPPORT_EMAIL}.

If you did not create a Toon Ranks account, you can safely ignore this email.

Thanks,
The Toon Ranks team
"""

    html = f"""\
<!doctype html>
<html>
  <body style="margin:0;background:#ffffff;font-family:Arial,Helvetica,sans-serif;color:#34364a;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
      Finish creating your Toon Ranks account by verifying your email address.
    </div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#ffffff;">
      <tr>
        <td align="center" style="padding:72px 20px 40px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:420px;">
            <tr>
              <td align="left" style="padding:0 0 26px;">
                <table role="presentation" cellspacing="0" cellpadding="0" style="border:1px solid #e8eaf2;border-radius:999px;background:#ffffff;">
                  <tr>
                    <td style="padding:8px 14px 8px 10px;">
                      <table role="presentation" cellspacing="0" cellpadding="0">
                        <tr>
                          <td style="vertical-align:middle;">
                            <img src="{escaped_logo_url}" width="34" height="34" alt="" style="display:block;border-radius:10px;border:0;">
                          </td>
                          <td style="vertical-align:middle;padding-left:10px;font-size:14px;line-height:18px;font-weight:800;letter-spacing:3px;color:#26283a;">
                            TOON RANKS
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td align="left">
                <h1 style="margin:0;color:#3b3d55;font-size:28px;line-height:36px;font-weight:500;letter-spacing:0;">
                  Verify your email address
                </h1>
                <p style="margin:18px 0 0;color:#555971;font-size:15px;line-height:24px;">
                  Welcome to Toon Ranks. Confirm this email to finish creating your account and start saving, rating, and discussing series with your profile.
                </p>
                <p style="margin:20px 0 0;">
                  <a href="{escaped_verify_url}" style="display:inline-block;background:#4f6df5;color:#ffffff;text-decoration:none;font-size:14px;line-height:20px;font-weight:700;padding:12px 26px;border-radius:999px;">
                    Verify your email
                  </a>
                </p>
                <p style="margin:22px 0 0;color:#555971;font-size:14px;line-height:22px;">
                  If you have any questions, just reply to this email.
                </p>
                <p style="margin:24px 0 0;color:#555971;font-size:14px;line-height:22px;">
                  Thanks,<br>
                  <em>The Toon Ranks team</em>
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:26px 0 0;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td style="border-top:1px solid #eef0f6;font-size:1px;line-height:1px;">&nbsp;</td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td align="left" style="padding:18px 0 0;color:#8a8da1;font-size:12px;line-height:20px;">
                <p style="margin:0;">
                  Sent with care from<br>
                  Toon Ranks by {escape(OPERATOR_NAME)}<br>
                  <a href="{escape(SITE_ORIGIN, quote=True)}" style="color:#6f748a;text-decoration:none;">toonranks.com</a>
                </p>
                <p style="margin:16px 0 0;">
                  Need help? Reply to this email or contact
                  <a href="mailto:{escape(SUPPORT_EMAIL, quote=True)}" style="color:#6f748a;text-decoration:underline;">{escape(SUPPORT_EMAIL)}</a>.
                </p>
                <p style="margin:16px 0 0;">
                  This verification link expires in 1 hour. If you did not create a Toon Ranks account, no action is needed.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 0 0;">
                <p style="margin:0;word-break:break-all;color:#9ca0b3;font-size:11px;line-height:18px;">
                  Button not working? Paste this link into your browser:<br>
                  <a href="{escaped_verify_url}" style="color:#6f748a;">{escaped_verify_url}</a>
                </p>
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
