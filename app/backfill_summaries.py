"""Summarize every message that has no summary yet.

    python -m app.backfill_summaries             # fill them in
    python -m app.backfill_summaries --dry-run   # only count them

Safe to run any number of times: a message that is already done is skipped.
Each summary is a real model call, so run --dry-run first to see how many
there are.
"""

import argparse
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_llm
from app.backfill_embeddings import BackfillReport
from app.core.db import async_session_factory, engine
from app.llm.base import LLMClient
from app.services.summary import find_unsummarized, summarize_message


async def backfill(
    session_factory: async_sessionmaker[AsyncSession],
    llm: LLMClient,
    dry_run: bool = False,
):
    """Find every message without a summary, and summarize each one."""

    async with session_factory() as session:
        missing = await find_unsummarized(session)

        if dry_run:
            return BackfillReport(missing=len(missing), filled=0, failed=0)

        filled = failed = 0

        for message_id in missing:
            try:
                if await summarize_message(session, llm, message_id):
                    filled += 1
            except Exception as exc:
                # One bad message should not stop the rest. Report it and carry
                # on; the next run will try it again.
                failed += 1
                await session.rollback()
                print(f"  failed {message_id}: {exc}")

        return BackfillReport(missing=len(missing), filled=filled, failed=failed)


async def run(dry_run: bool):
    try:
        report = await backfill(async_session_factory, get_llm(), dry_run)
    finally:
        await engine.dispose()

    print(f"{report.missing} messages had no summary")
    if not dry_run:
        print(f"filled {report.filled}, failed {report.failed}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="only count, summarize nothing"
    )
    args = parser.parse_args()
    asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    main()
