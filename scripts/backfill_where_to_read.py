"""Fill series.where_to_read from AniList for titles that already exist.

AniList-linked titles are looked up by their stored id. Titles entered manually are
matched by exact title (the same strict matcher used for new submissions); anything
without an exact match is skipped, never guessed. Only where_to_read is written.

Dry run by default — pass --apply to save.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.database import AsyncSessionLocal, engine
from app.models import reading_list as _reading_list  # noqa: F401
from app.models.series_model import Series, SeriesApprovalStatus
from app.schemas.series_schemas import SeriesTypeEnum
from app.utils.external_catalog import find_anilist_match_for_title, get_anilist_title

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


async def _lookup(series: Series):
    if series.external_source == "ANILIST" and series.external_id:
        return await get_anilist_title(series.external_id), "id"
    series_type = _series_type(series.type)
    if not series_type:
        return None, "unsupported type"
    return await find_anilist_match_for_title(series.title, series_type), "title"


async def backfill(limit: int | None, delay: float, apply: bool, overwrite: bool) -> None:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Series)
            .where(Series.approval_status == SeriesApprovalStatus.APPROVED.value)
            .order_by(Series.id.asc())
        )
        if not overwrite:
            stmt = stmt.where(Series.where_to_read.is_(None))
        if limit:
            stmt = stmt.limit(limit)

        rows = (await session.execute(stmt)).scalars().all()
        filled = no_links = no_match = failed = 0

        for index, series in enumerate(rows, start=1):
            prefix = f"[{index}/{len(rows)}] {series.id} {_safe(series.title)!r}"
            candidate, how = None, ""
            for attempt in range(1, 4):
                try:
                    candidate, how = await _lookup(series)
                    break
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 429 and attempt < 3:
                        print(f"{prefix}: rate limited; waiting {75 * attempt}s")
                        await asyncio.sleep(75 * attempt)
                        continue
                    print(f"{prefix}: error {_safe(exc)}")
                    how = "error"
                    break
                except Exception as exc:
                    print(f"{prefix}: error {_safe(exc)}")
                    how = "error"
                    break

            if how == "error":
                failed += 1
            elif not candidate:
                no_match += 1
                print(f"{prefix}: no exact AniList match ({how})")
            elif not candidate.reading_links:
                no_links += 1
                print(f"{prefix}: matched by {how}, AniList lists no English platforms")
            else:
                filled += 1
                sites = ", ".join(link["site"] for link in candidate.reading_links)
                print(f"{prefix}: matched by {how} -> {sites}")
                if apply:
                    series.where_to_read = candidate.reading_links
                    await session.commit()

            await asyncio.sleep(delay)

        if not apply:
            await session.rollback()

    print(
        f"Done. filled={filled} no_links={no_links} no_match={no_match} "
        f"failed={failed} applied={apply}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Where to read links from AniList.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum titles to process.")
    parser.add_argument("--delay", type=float, default=0.8, help="Seconds between requests.")
    parser.add_argument("--apply", action="store_true", help="Save results (default: dry run).")
    parser.add_argument(
        "--overwrite", action="store_true", help="Also refresh titles that already have links."
    )
    args = parser.parse_args()

    async def run() -> None:
        try:
            await backfill(args.limit, args.delay, args.apply, args.overwrite)
        finally:
            await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
