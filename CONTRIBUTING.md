# Contributing (Backend – FastAPI)

## Branch naming

Create a branch before doing any work — **never commit directly to `main`**.

Preferred pattern: `backend-<short-desc>`
Examples:
- `backend-fix-vote-count`
- `backend-forum-read-state`
- `backend-cors-env-origins`

If you use Jira: `TR-###-<dev>-<short-desc>` (e.g. `TR-8-kin-pr-template`)

---

## Local setup

```bash
# 1. Clone and enter the repo
git clone https://github.com/trulyepic/toonranks-backend.git
cd toonranks-backend

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# 3. Install runtime + dev dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 4. Create your local env file
cp .env.example .env            # fill in values — see required vars below

# 5. Start the dev server
uvicorn app.main:app --reload --port 8000
```

API docs available at `http://localhost:8000/docs`.

### Required environment variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | `postgresql://user:pass@host/db` |
| `SECRET_KEY` | JWT signing key, minimum 32 characters |
| `AWS_ACCESS_KEY_ID` | S3 access (required for image uploads) |
| `AWS_SECRET_ACCESS_KEY` | S3 secret |
| `AWS_REGION` | e.g. `us-east-1` |
| `AWS_BUCKET_NAME` | S3 bucket name |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `SENDGRID_API_KEY` | Transactional email |
| `RECAPTCHA_SECRET_KEY` | reCAPTCHA v2 secret key |

For a full reference including optional vars, see `CLAUDE.md`.

---

## Running tests

```bash
# All tests (mocked — no live DB or external services needed)
pytest

# Verbose
pytest -v -s

# Single file
pytest tests/auth_test.py

# Integration tests (requires TEST_DATABASE_URL set in env)
pytest -m integration

# Regression tests only
pytest -m regression
```

---

## Linting

```bash
# Check
ruff check .

# Auto-fix safe issues
ruff check . --fix
```

Line length is **100**. Run linting before opening a PR.

---

## Before opening a PR

- [ ] Branch is off `main`, not committed to `main` directly
- [ ] `ruff check .` passes with no errors
- [ ] `pytest` passes (excluding integration tests if no DB available)
- [ ] New route or utility has a corresponding test in `tests/`
- [ ] Any new model includes `__table_args__ = {"schema": "man_review"}`
- [ ] Any new DB column has an idempotent `ALTER TABLE IF NOT EXISTS` in `main.py`'s `on_startup`
- [ ] `requirements.txt` updated if a new dependency was added

---

## Key reference docs

| Doc | What it covers |
|---|---|
| `CLAUDE.md` | AI assistant entry point — project overview, rules, patterns |
| `AGENTS.md` | Universal agent instructions (Cursor, Copilot, Windsurf) |
| `docs/ARCHITECTURE.md` | System overview, deployment, request lifecycle |
| `docs/DATA_MODEL.md` | All tables, columns, FKs, enums |
| `docs/API.md` | Full endpoint inventory |
| `docs/CONVENTIONS.md` | Coding patterns — sessions, auth, pagination, errors |
