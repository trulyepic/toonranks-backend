import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.database import AsyncSessionLocal, engine
from app.models import reading_list as _reading_list  # noqa: F401
from app.models.series_model import Series, SeriesApprovalStatus
from app.routes.series_routes import _apply_external_metadata, _external_metadata_in_use
from app.schemas.series_schemas import SeriesTypeEnum
from app.utils.external_catalog import find_anilist_match_for_title

engine.echo = False


def _safe(value: object) -> str:
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def _series_type(value) -> SeriesTypeEnum | None:
    if not value:
        return None
    raw_value = value.value if hasattr(value, "value") else str(value)
    try:
        return SeriesTypeEnum(raw_value)
    except ValueError:
        return None


async def backfill(limit: int | None, delay: float, dry_run: bool) -> None:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Series)
            .where(
                Series.approval_status == SeriesApprovalStatus.APPROVED.value,
                Series.external_score.is_(None),
                Series.external_popularity.is_(None),
            )
            .order_by(Series.id.asc())
        )
        if limit:
            stmt = stmt.limit(limit)

        rows = (await session.execute(stmt)).scalars().all()
        matched = 0
        skipped = 0

        for index, series in enumerate(rows, start=1):
            series_type = _series_type(series.type)
            if not series_type:
                skipped += 1
                print(f"[{index}/{len(rows)}] skip {series.id} {_safe(series.title)!r}: unsupported type")
                continue

            candidate = None
            failed = False
            for attempt in range(1, 4):
                try:
                    candidate = await find_anilist_match_for_title(series.title, series_type)
                    break
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 429 and attempt < 3:
                        wait_seconds = 75 * attempt
                        print(
                            f"[{index}/{len(rows)}] rate limited on {series.id} "
                            f"{_safe(series.title)!r}; waiting {wait_seconds}s"
                        )
                        await asyncio.sleep(wait_seconds)
                        continue
                    skipped += 1
                    failed = True
                    print(f"[{index}/{len(rows)}] skip {series.id} {_safe(series.title)!r}: {_safe(exc)}")
                    break
                except Exception as exc:
                    skipped += 1
                    failed = True
                    print(f"[{index}/{len(rows)}] skip {series.id} {_safe(series.title)!r}: {_safe(exc)}")
                    break

            if failed:
                await asyncio.sleep(delay)
                continue

            if not candidate:
                skipped += 1
                print(f"[{index}/{len(rows)}] no match {series.id} {_safe(series.title)!r}")
                await asyncio.sleep(delay)
                continue

            matched += 1
            print(
                f"[{index}/{len(rows)}] match {series.id} {_safe(series.title)!r} -> "
                f"{_safe(candidate.title)!r} ({candidate.external_id}) "
                f"score={candidate.average_score} popularity={candidate.popularity}"
            )
            if not dry_run:
                if await _external_metadata_in_use(session, candidate, series.id):
                    skipped += 1
                    matched -= 1
                    print(
                        f"[{index}/{len(rows)}] skip {series.id} {_safe(series.title)!r}: "
                        f"{candidate.source} {candidate.external_id} already linked"
                    )
                    await asyncio.sleep(delay)
                    continue
                _apply_external_metadata(series, candidate)
                series.external_synced_at = datetime.now(timezone.utc).isoformat()
                await session.commit()

            await asyncio.sleep(delay)

        if dry_run:
            await session.rollback()

    print(f"Done. matched={matched} skipped={skipped} dry_run={dry_run}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill AniList metrics for existing ToonRanks titles.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of titles to process.")
    parser.add_argument("--delay", type=float, default=0.8, help="Delay between AniList requests in seconds.")
    parser.add_argument("--dry-run", action="store_true", help="Print matches without updating the database.")
    args = parser.parse_args()
    async def run() -> None:
        try:
            await backfill(args.limit, args.delay, args.dry_run)
        finally:
            await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
