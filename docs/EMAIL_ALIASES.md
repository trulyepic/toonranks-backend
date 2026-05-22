# Toon Ranks Email Aliases

Toon Ranks uses purpose-specific aliases so account, support, billing, and internal messages are easier to identify and route.

## Current Aliases

| Purpose | Alias | Backend usage |
| --- | --- | --- |
| Signup verification | `noreply@toonranks.com` | Sender for account verification emails. |
| Password reset | `accounts@toonranks.com` | Sender for password reset and account recovery emails. |
| Human support/contact | `support@toonranks.com` | Public support address and reply-to address for auth emails. |
| Billing/subscription | `billing@toonranks.com` | Reserved for future subscription, invoice, and billing support flows. |
| Internal/admin alerts | `admin@toonranks.com` | Reserved for future operational and admin notifications. |

## Runtime Variables

When configuring email in production, set the SMTP host, port, username, and password in the hosting provider's secret manager. Do not commit concrete SMTP passwords or app passwords.

Use these non-secret alias values:

| Variable | Value |
| --- | --- |
| `VERIFICATION_FROM_EMAIL` | `noreply@toonranks.com` |
| `PASSWORD_RESET_FROM_EMAIL` | `accounts@toonranks.com` |
| `FROM_NAME` | `Toon Ranks` |
| `SUPPORT_EMAIL` | `support@toonranks.com` |
| `BILLING_EMAIL` | `billing@toonranks.com` |
| `ADMIN_ALERT_EMAIL` | `admin@toonranks.com` |
| `OPERATOR_NAME` | `Nofara LLC` |

Before switching production mail traffic, confirm the SMTP provider is authorized to send as each alias. Auth emails set `Reply-To` to `support@toonranks.com` so users can still reach a person if they need help.
