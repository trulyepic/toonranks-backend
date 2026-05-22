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
VERIFICATION_FROM_EMAIL = os.getenv("VERIFICATION_FROM_EMAIL")
VERIFICATION_FROM_EMAIL = VERIFICATION_FROM_EMAIL or "noreply@toonranks.com"
PASSWORD_RESET_FROM_EMAIL = os.getenv("PASSWORD_RESET_FROM_EMAIL")
PASSWORD_RESET_FROM_EMAIL = PASSWORD_RESET_FROM_EMAIL or "accounts@toonranks.com"
BILLING_EMAIL = os.getenv("BILLING_EMAIL", "billing@toonranks.com")
ADMIN_ALERT_EMAIL = os.getenv("ADMIN_ALERT_EMAIL", "admin@toonranks.com")
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
    from_email = VERIFICATION_FROM_EMAIL

    verify_url = f"{SITE_ORIGIN}/verify-email?token={token}"
    subject = "Verify your Toon Ranks email address"
    escaped_verify_url = escape(verify_url, quote=True)
    escaped_logo_url = escape(LOGO_URL, quote=True)

    text = f"""Hi there,

Welcome to Toon Ranks. Verify your email address to finish setting up your reader profile.

{verify_url}

This link expires in 1 hour. If future Toon Ranks emails land in your Spam folder,
mark them as Not Spam so verification and support messages arrive normally.

If you have questions, contact {SUPPORT_EMAIL}.

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
        <td align="center" style="padding:64px 20px 40px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:440px;">
            <tr>
              <td align="center" style="padding:0 0 28px;">
                <table role="presentation" cellspacing="0" cellpadding="0" style="border:1px solid #e7edf5;border-radius:18px;background:#ffffff;box-shadow:0 10px 24px rgba(15,23,42,0.05);">
                  <tr>
                    <td style="padding:10px 16px 10px 12px;">
                      <table role="presentation" cellspacing="0" cellpadding="0">
                        <tr>
                          <td style="vertical-align:middle;">
                            <img src="{escaped_logo_url}" width="42" height="42" alt="" style="display:block;border-radius:12px;border:0;">
                          </td>
                          <td style="vertical-align:middle;padding-left:12px;font-size:13px;line-height:18px;font-weight:800;letter-spacing:2.8px;color:#182235;">
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
                <div style="margin:0 0 18px;width:54px;height:4px;background:#74c7f7;border-radius:999px;"></div>
                <h1 style="margin:0;color:#243044;font-size:30px;line-height:38px;font-weight:700;letter-spacing:0;">
                  Confirm your Toon Ranks email
                </h1>
                <p style="margin:16px 0 0;color:#556074;font-size:15px;line-height:24px;">
                  One quick step and your profile is ready for saved series, category ratings, and forum discussions.
                </p>
                <p style="margin:22px 0 0;">
                  <a href="{escaped_verify_url}" style="display:inline-block;background:#1f8bd6;color:#ffffff;text-decoration:none;font-size:14px;line-height:20px;font-weight:700;padding:13px 26px;border-radius:12px;">
                    Confirm email
                  </a>
                </p>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:26px 0 0;border:1px solid #e7edf5;border-radius:16px;background:#f8fbff;">
                  <tr>
                    <td style="padding:16px 18px;color:#5d6878;font-size:13px;line-height:21px;">
                      This verification link expires in 1 hour. If this email landed in Spam, mark it as Not Spam before using the link so future Toon Ranks messages arrive normally.
                    </td>
                  </tr>
                </table>
                <p style="margin:22px 0 0;color:#556074;font-size:14px;line-height:22px;">
                  Questions or trouble signing in? Contact support and we will help.
                </p>
                <p style="margin:24px 0 0;color:#556074;font-size:14px;line-height:22px;">
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
              <td align="left" style="padding:18px 0 0;color:#8792a3;font-size:12px;line-height:20px;">
                <p style="margin:0;">
                  Sent with care from<br>
                  Toon Ranks by {escape(OPERATOR_NAME)}<br>
                  <a href="{escape(SITE_ORIGIN, quote=True)}" style="color:#68778a;text-decoration:none;">toonranks.com</a>
                </p>
                <p style="margin:16px 0 0;">
                  Need help? Contact
                  <a href="mailto:{escape(SUPPORT_EMAIL, quote=True)}" style="color:#68778a;text-decoration:underline;">{escape(SUPPORT_EMAIL)}</a>.
                </p>
                <p style="margin:16px 0 0;">
                  This verification link expires in 1 hour. If you did not create a Toon Ranks account, no action is needed.
                </p>
                <p style="margin:16px 0 0;">
                  If this message was filtered to Spam, mark it as Not Spam to help your inbox recognize Toon Ranks.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 0 0;">
                <p style="margin:0;word-break:break-all;color:#9aa4b5;font-size:11px;line-height:18px;">
                  Button not working? Paste this link into your browser:<br>
                  <a href="{escaped_verify_url}" style="color:#68778a;">{escaped_verify_url}</a>
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
    msg["Reply-To"] = SUPPORT_EMAIL
    msg["Message-ID"] = make_msgid(domain=_message_id_domain(from_email))
    msg["X-Auto-Response-Suppress"] = "All"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def _build_password_reset_email(to_email: str, token: str) -> EmailMessage:
    from_email = PASSWORD_RESET_FROM_EMAIL

    reset_url = f"{SITE_ORIGIN}/reset-password?token={token}"
    subject = "Reset your Toon Ranks password"
    escaped_reset_url = escape(reset_url, quote=True)
    escaped_logo_url = escape(LOGO_URL, quote=True)

    text = f"""Hi there,

We received a request to reset your Toon Ranks password.

{reset_url}

This link expires in 30 minutes. If you did not request a password reset, you can
safely ignore this email and your password will stay the same.

Thanks,
The Toon Ranks team
"""

    html = f"""\
<!doctype html>
<html>
  <body style="margin:0;background:#ffffff;font-family:Arial,Helvetica,sans-serif;color:#34364a;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
      Reset your Toon Ranks password. This link expires in 30 minutes.
    </div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#ffffff;">
      <tr>
        <td align="center" style="padding:64px 20px 40px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:440px;">
            <tr>
              <td align="center" style="padding:0 0 28px;">
                <table role="presentation" cellspacing="0" cellpadding="0" style="border:1px solid #e7edf5;border-radius:18px;background:#ffffff;box-shadow:0 10px 24px rgba(15,23,42,0.05);">
                  <tr>
                    <td style="padding:10px 16px 10px 12px;">
                      <table role="presentation" cellspacing="0" cellpadding="0">
                        <tr>
                          <td style="vertical-align:middle;">
                            <img src="{escaped_logo_url}" width="42" height="42" alt="" style="display:block;border-radius:12px;border:0;">
                          </td>
                          <td style="vertical-align:middle;padding-left:12px;font-size:13px;line-height:18px;font-weight:800;letter-spacing:2.8px;color:#182235;">
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
                <div style="margin:0 0 18px;width:54px;height:4px;background:#74c7f7;border-radius:999px;"></div>
                <h1 style="margin:0;color:#243044;font-size:30px;line-height:38px;font-weight:700;letter-spacing:0;">
                  Reset your password
                </h1>
                <p style="margin:16px 0 0;color:#556074;font-size:15px;line-height:24px;">
                  Use the button below to choose a new password for your Toon Ranks account.
                </p>
                <p style="margin:22px 0 0;">
                  <a href="{escaped_reset_url}" style="display:inline-block;background:#1f8bd6;color:#ffffff;text-decoration:none;font-size:14px;line-height:20px;font-weight:700;padding:13px 26px;border-radius:12px;">
                    Reset password
                  </a>
                </p>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:26px 0 0;border:1px solid #e7edf5;border-radius:16px;background:#f8fbff;">
                  <tr>
                    <td style="padding:16px 18px;color:#5d6878;font-size:13px;line-height:21px;">
                      This reset link expires in 30 minutes. If you did not request it, you can ignore this email and your password will stay the same.
                    </td>
                  </tr>
                </table>
                <p style="margin:22px 0 0;color:#556074;font-size:14px;line-height:22px;">
                  Questions or trouble signing in? Contact support and we will help.
                </p>
                <p style="margin:24px 0 0;color:#556074;font-size:14px;line-height:22px;">
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
              <td align="left" style="padding:18px 0 0;color:#8792a3;font-size:12px;line-height:20px;">
                <p style="margin:0;">
                  Sent with care from<br>
                  Toon Ranks by {escape(OPERATOR_NAME)}<br>
                  <a href="{escape(SITE_ORIGIN, quote=True)}" style="color:#68778a;text-decoration:none;">toonranks.com</a>
                </p>
                <p style="margin:16px 0 0;">
                  Need help? Contact
                  <a href="mailto:{escape(SUPPORT_EMAIL, quote=True)}" style="color:#68778a;text-decoration:underline;">{escape(SUPPORT_EMAIL)}</a>.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 0 0;">
                <p style="margin:0;word-break:break-all;color:#9aa4b5;font-size:11px;line-height:18px;">
                  Button not working? Paste this link into your browser:<br>
                  <a href="{escaped_reset_url}" style="color:#68778a;">{escaped_reset_url}</a>
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
    msg["Reply-To"] = SUPPORT_EMAIL
    msg["Message-ID"] = make_msgid(domain=_message_id_domain(from_email))
    msg["X-Auto-Response-Suppress"] = "All"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def _send_email(to_email: str, msg: EmailMessage, from_email: str):
    smtp_host = _required_env("SMTP_HOST")
    smtp_username = _required_env("SMTP_USERNAME")
    smtp_password = _required_env("SMTP_PASSWORD")

    with smtplib.SMTP(smtp_host, _smtp_port()) as server:
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.send_message(msg, from_addr=from_email, to_addrs=[to_email])


def send_verification_email(to_email: str, token: str):
    msg = _build_verification_email(to_email, token)

    try:
        _send_email(to_email, msg, VERIFICATION_FROM_EMAIL)
    except Exception as e:
        print("SMTP send failed:", e)
        raise


def send_password_reset_email(to_email: str, token: str):
    msg = _build_password_reset_email(to_email, token)

    try:
        _send_email(to_email, msg, PASSWORD_RESET_FROM_EMAIL)
    except Exception as e:
        print("SMTP send failed:", e)
        raise
