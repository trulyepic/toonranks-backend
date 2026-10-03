# External Catalog Import Plan

Purpose: let admins batch-discover manga, manhwa, and manhua from external catalog data, import selected or batched candidates into ToonRanks as pending titles, review/edit them, then approve only the titles that should appear on the public frontend.

Primary source: AniList GraphQL API.

Core rule: imported catalog data is never public by default. Every imported title enters the existing pending-title review queue and only appears publicly after admin approval.

## Guiding Decisions

- Use AniList first because it supports manga-style media with title, country of origin, description, genres, status, cover images, popularity, and score.
- Do not add anime support.
- Infer ToonRanks type from AniList country:
  - `JP` -> `MANGA`
  - `KR` -> `MANHWA`
  - `CN`, `TW`, `HK` -> `MANHUA`
- Store source identity on every imported title:
  - `external_source`
  - `external_id`
  - `external_url`
- Prevent duplicates by enforcing uniqueness on `(external_source, external_id)` when both values exist.
- Keep imports admin-only.
- Keep the approval queue as the final gate before frontend visibility.

## Phase 1: Source Identity And Single Import Foundation

- [x] Add nullable source identity fields to `Series`.
- [x] Add startup migration for source identity fields.
- [x] Add unique partial index for source identity duplicate prevention.
- [x] Include source identity fields in series API response schemas.
- [x] Add AniList normalization utility.
- [x] Add admin-only external catalog search endpoint.
- [x] Add admin-only single-title import endpoint.
- [x] Ensure imported titles are created as `PENDING`.
- [x] Ensure duplicate imports return the existing title instead of creating a duplicate.
- [x] Add backend tests for normalization, import, and duplicate handling.
- [x] Add basic admin UI to search and import a single candidate.

## Phase 2: Batch Discovery

- [x] Add backend discovery function that queries AniList without a title search.
- [x] Support batch discovery filters:
  - [x] ToonRanks type: `MANGA`, `MANHWA`, `MANHUA`
  - [x] Sort: `POPULARITY_DESC`, `TRENDING_DESC`, `SCORE_DESC`, `START_DATE_DESC`
  - [x] Page number
  - [x] Page size, capped at AniList max page size
  - [x] Optional genre filter
- [x] Normalize batch candidates into the same candidate shape used by single search.
- [x] Add backend tests for batch discovery normalization and batch import behavior.

## Phase 3: Batch Import

- [x] Add admin-only batch import endpoint.
- [x] Request shape:

```json
{
  "type": "MANHWA",
  "sort": "POPULARITY_DESC",
  "page": 1,
  "page_size": 50,
  "genre": "Action"
}
```

- [x] Response shape:

```json
{
  "imported": 43,
  "duplicates": 7,
  "skipped": 0,
  "items": []
}
```

- [ ] For every discovered candidate:
  - [x] Skip unsupported countries.
  - [x] Skip candidates missing a title.
  - [x] Skip or record duplicates using `external_source + external_id`.
  - [x] Create new rows as `PENDING`.
  - [x] Create `SeriesDetail` when synopsis or detail cover exists.
- [x] Add transaction handling so duplicates do not modify existing rows and all-duplicate batches do not commit.
- [x] Add backend tests for imported, duplicate, and all-duplicate batch results.

## Phase 4: Admin Review UI

- [x] Add a batch import panel to the pending-title admin page.
- [ ] Controls:
  - [x] Type selector
  - [x] Sort selector
  - [x] Page selector
  - [x] Page size selector
  - [x] Optional genre input/select
- [x] Add a preview step before import.
- [x] Show per-candidate source, type, genre, cover, and popularity/score.
- [x] Let admin import all previewed new candidates.
- [x] Show import summary: imported, duplicates, skipped.
- [x] Add source badges/links in pending-title cards.
- [x] Keep existing edit, preview, approve, and delete actions.

## Phase 5: Review Quality And Safety

- [ ] Add admin warning copy that imported metadata should be checked before approval.
- [ ] Keep public rankings/search filtered to `APPROVED` only.
- [ ] Confirm sitemap only includes approved imported titles.
- [ ] Confirm contributors cannot access import endpoints.
- [ ] Confirm regular users cannot access import endpoints.
- [ ] Confirm duplicate prevention still works if two admins import the same batch close together.

## Phase 6: Optional Enhancements

- [ ] Add `external_score` and `external_popularity` columns if admins want sorting context preserved after import.
- [ ] Add `external_synced_at` if future refresh/update support is needed.
- [ ] Add source-specific attribution display if required.
- [ ] Add Jikan fallback for titles missing from AniList.
- [ ] Add MangaDex only if its acceptable-use policy fits ToonRanks monetization.

## Verification Checklist

- [x] Backend targeted tests pass for current foundation.
- [x] Frontend typecheck passes with no incremental cache writes.
- [x] Frontend production build passes.
- [x] Backend tests pass after batch discovery/import implementation.
- [x] Frontend typecheck passes after batch UI implementation.
- [x] Frontend production build passes after batch UI implementation.
- [x] Live AniList batch discovery query returns expected manga/manhwa/manhua metadata shape.
- [ ] Manual admin flow verified:
  - [ ] Batch discover candidates.
  - [ ] Preview candidates.
  - [ ] Import candidates.
  - [ ] Confirm duplicates are skipped.
  - [ ] Edit imported pending title.
  - [ ] Approve imported pending title.
  - [ ] Confirm approved title appears publicly.
  - [ ] Confirm rejected title can be deleted.

## Out Of Scope For This Import Work

- User-facing public browsing of external catalogs before import.
- Automatic public publishing of external titles.
- Anime support.
- Chapter reading or scanlation content.
- Bulk scraping outside official/free API access.
