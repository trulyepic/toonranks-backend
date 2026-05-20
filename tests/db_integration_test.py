import importlib
import os

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.database import Base
from app.models.reading_list import ReadingList, ReadingListItem
from app.models.series_model import Series, SeriesStatus, SeriesType
from app.models.user_model import User


pytestmark = pytest.mark.integration


MODEL_MODULES = [
    "app.models.forum_media_model",
    "app.models.forum_model",
    "app.models.issue",
    "app.models.mobile_auth_code",
    "app.models.reading_list",
    "app.models.series_detail",
    "app.models.series_model",
    "app.models.user_model",
    "app.models.user_vote",
]


def load_models_for_metadata():
    for module_name in MODEL_MODULES:
        importlib.import_module(module_name)


def get_test_database_url():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not set")
    forbidden_fragments = ("railway.app", "amazonaws.com", "prod", "production")
    if any(fragment in database_url.lower() for fragment in forbidden_fragments):
        pytest.fail("TEST_DATABASE_URL must point to a disposable test database")
    return database_url.replace("postgresql://", "postgresql+asyncpg://")


async def prepare_schema(conn):
    await conn.execute(text('CREATE SCHEMA IF NOT EXISTS "man_review";'))
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto;"))
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_type t
                    JOIN pg_namespace n ON n.oid = t.typnamespace
                    WHERE t.typname = 'series_status'
                    AND n.nspname = 'man_review'
                ) THEN
                    CREATE TYPE man_review.series_status AS ENUM (
                        'ONGOING',
                        'COMPLETE',
                        'HIATUS',
                        'UNKNOWN',
                        'SEASON_END'
                    );
                END IF;
            END
            $$;
            """
        )
    )


@pytest.mark.anyio
async def test_database_metadata_and_user_crud_round_trip():
    database_url = get_test_database_url()
    load_models_for_metadata()
    engine = create_async_engine(database_url, echo=False, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with engine.begin() as conn:
            await prepare_schema(conn)
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            user = User(
                username="integration-reader",
                password="hashed-password",
                email="integration@example.com",
                is_verified=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

            found = await session.get(User, user.id)
            assert found is not None
            assert found.username == "integration-reader"
            assert found.email == "integration@example.com"

            await session.delete(found)
            await session.commit()
            assert await session.get(User, user.id) is None
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.mark.anyio
async def test_database_user_series_and_reading_list_crud_flow():
    database_url = get_test_database_url()
    load_models_for_metadata()
    engine = create_async_engine(database_url, echo=False, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with engine.begin() as conn:
            await prepare_schema(conn)
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            user = User(
                username="reading-list-reader",
                password="hashed-password",
                email="reading-list@example.com",
                is_verified=True,
            )
            series = Series(
                title="Integration Series",
                genre="Action",
                type=SeriesType.MANHWA,
                status=SeriesStatus.ONGOING,
                approval_status="APPROVED",
            )
            session.add_all([user, series])
            await session.commit()
            await session.refresh(user)
            await session.refresh(series)

            reading_list = ReadingList(user_id=user.id, name="Weekend Reads")
            session.add(reading_list)
            await session.commit()
            await session.refresh(reading_list)

            item = ReadingListItem(
                list_id=reading_list.id,
                series_id=series.id,
                left_off_chapter="Chapter 12",
            )
            session.add(item)
            await session.commit()

            result = await session.execute(
                select(ReadingList)
                .where(ReadingList.id == reading_list.id)
                .options(selectinload(ReadingList.items))
            )
            found_list = result.scalars().first()

            assert found_list is not None
            assert found_list.user_id == user.id
            assert found_list.share_token is not None
            assert len(found_list.items) == 1
            assert found_list.items[0].series_id == series.id
            assert found_list.items[0].left_off_chapter == "Chapter 12"

            await session.delete(user)
            await session.commit()

            list_count = (
                await session.execute(select(func.count(ReadingList.id)))
            ).scalar_one()
            item_count = (
                await session.execute(select(func.count(ReadingListItem.id)))
            ).scalar_one()
            series_count = (await session.execute(select(func.count(Series.id)))).scalar_one()

            assert list_count == 0
            assert item_count == 0
            assert series_count == 1
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
