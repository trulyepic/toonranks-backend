import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import DATABASE_URL
from app.models import reading_list as _reading_list  # noqa: F401
from app.models.series_model import Series
from app.routes.series_routes import _apply_external_metadata
from app.utils.external_catalog import get_anilist_title

engine = create_async_engine(
    DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
    connect_args={"ssl": "require"},
)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def backfill(titles: list[str], dry_run: bool) -> None:
    normalized_titles = {title.strip().casefold() for title in titles if title.strip()}
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(Series)
                .where(func.lower(Series.title).in_(normalized_titles))
                .order_by(Series.id.asc())
            )
        ).scalars().all()

        matched_titles = {series.title.casefold() for series in rows}
        for missing in sorted(normalized_titles - matched_titles):
            print(f"not found: {missing!r}")

        updated = 0
        skipped = 0
        for series in rows:
            if (series.external_source or "").upper() != "ANILIST" or not series.external_id:
                skipped += 1
                print(
                    f"skip id={series.id} title={series.title!r} status={series.approval_status}: "
                    "not linked to AniList"
                )
                continue

            candidate = await get_anilist_title(series.external_id)
            if not candidate:
                skipped += 1
                print(
                    f"skip id={series.id} title={series.title!r}: "
                    f"AniList id {series.external_id} was not found"
                )
                continue

            print(
                f"update id={series.id} title={series.title!r} status={series.approval_status} "
                f"anilist_id={candidate.external_id} "
                f"stored_score={series.external_score} stored_popularity={series.external_popularity} "
                f"anilist_score={candidate.average_score} anilist_popularity={candidate.popularity}"
            )
            _apply_external_metadata(series, candidate)
            updated += 1

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

    print(f"Done. updated={updated} skipped={skipped} dry_run={dry_run}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill AniList metrics for explicitly selected imported titles."
    )
    parser.add_argument(
        "--title",
        action="append",
        required=True,
        help="Exact ToonRanks title to refresh. Repeat for multiple titles.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without updating the database.")
    args = parser.parse_args()

    async def run() -> None:
        try:
            await backfill(args.title, args.dry_run)
        finally:
            await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
