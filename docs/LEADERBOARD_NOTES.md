# Leaderboard (Rankers) — Notes

Endpoints: `GET /users/leaderboard` (list) and `GET /users/{username}` (per-profile rank).

## Current behavior (as of backend-leaderboard-all-users)

- **All non-admin users are ranked**, including newcomers with `cred_score = 0`.
- Ordering: `cred_score DESC, id ASC`. Zero-activity users sort to the bottom and
  climb as they earn cred. Ties break by `id` (older accounts first) so paging is stable.
- **Admins are excluded** from ranking entirely (`rank = null` on their profile).
  Do not change this.
- A user's profile rank uses the **same tie-break** as the list, so the number on
  their profile matches their position on the board.

## Known future consideration (not a problem yet)

With few users this is fine. **If the user base grows with many registered-but-inactive
accounts**, the board becomes long and tail-heavy with 0-cred users. Options when/if that
happens:

1. Keep as-is (paginated) — simplest.
2. Add a subtle visual split between **Ranked** (`cred_score > 0`) and **Newcomers**
   (`cred_score = 0`) on the frontend.
3. Add an optional `?active_only=true` query param to the leaderboard endpoint for an
   "active rankers only" view, while still letting every profile show a rank.

No action needed now — revisit when the tail gets noisy.
