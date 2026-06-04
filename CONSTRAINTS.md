# AI Assistant Constraints — Toon Ranks Backend

These rules apply to every AI assistant working in this repository without exception.
They are repeated in `CLAUDE.md`, `AGENTS.md`, and `.cursorrules` — if you are reading
any of those files, these constraints still apply.

---

## Workflow — how work gets shipped

```
AI creates feature branch
        │
        ▼
AI does the work on that branch
        │
        ▼
AI hands off:
  1. Test steps (API calls, UI steps, or pytest commands to verify the change)
  2. Short commit message
  3. Short GitHub PR description
        │
        ▼
Owner reviews — ONLY commits and pushes when explicitly told to
        │
        ▼
Owner creates PR → main
        │
        ▼
Railway auto-deploys on merge to main
```

---

## Hard constraints

### 1. Never commit or push without explicit instruction
Do not run `git commit`, `git push`, `git merge`, or open a PR unless the owner
explicitly says "commit", "push", or "commit and push". Completing a task does
**not** imply permission to commit. Always wait to be asked.

### 2. Always provide a handoff at the end of every task
When you finish work on a branch, always end your response with:

**Test steps** — how to verify the change works. For backend changes this is
typically a combination of:
- `pytest tests/my_feature_test.py` command
- API calls to make (method, URL, payload, expected response)
- Any UI steps on the frontend that exercise the endpoint

Example:
```
1. Run: pytest tests/auth_test.py -v
2. POST /auth/login with valid credentials — expected: 200 + access_token
3. POST /auth/login with wrong password — expected: 401 Invalid credentials
```

**Commit message** — one line, imperative, under 72 characters:
```
feat: add EXTRA_CORS_ORIGINS env-driven config for UAT support
```

**GitHub PR description** — short summary + test plan checklist:
```
## Summary
- Adds EXTRA_CORS_ORIGINS to config.py (comma-separated env var)
- Spreads into CORS allow_origins in main.py
- No code change needed to add new origins — set the env var in Railway

## Test plan
- [ ] pytest passes
- [ ] UAT origin accepted (check CORS headers in browser network tab)
- [ ] Production origins still work
```

### 3. One branch per task
Never mix unrelated changes on the same branch. If you notice something else
that needs fixing while working, flag it as a follow-up, do not fix it inline.

### 4. Never work directly on `main`
All work goes on a feature branch named `backend-<short-desc>`. The owner
merges to `main` via a PR after reviewing.

### 5. Ask before assuming on anything ambiguous
If a requirement is unclear, ask one focused question before writing code.
Do not make assumptions and build the wrong thing.

---

## Branch naming

`backend-<short-desc>`

Examples: `backend-cors-env-origins`, `backend-fix-vote-count`, `backend-forum-read-state`
