"""Embed every message that has no embedding yet.

    python -m app.backfill_embeddings             # fill them in
    python -m app.backfill_embeddings --dry-run   # only count them

Safe to run any number of times: a message that is already done is skipped.
"""

import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_llm
from app.core.db import async_session_factory,engine
from app.llm.base import LLMClient
from app.services.embedding import embed_message,find_unembedded


@dataclass(frozen=True)
class BackfillReport:
    missing:int 
    filled: int
    failed:int


async def backfill(
    session_factory: async_sessionmaker[AsyncSession],
    llm: LLMClient,
    dry_run: bool = False,
):
    """Find every message without an embedding, and embed each one."""

    async with session_factory() as session:
        missing = await find_unembedded(session)

        if dry_run:
            return BackfillReport(missing=len(missing), filled=0, failed=0)

        filled = failed = 0

        for message_id in missing:
            try:
                if await embed_message(session,llm,message_id):
                    filled+=1
            except Exception as exc:
                # One bad message should not stop the rest. Report it and carry
                # on; the next run will try it again.

                failed+=1
                await session.rollback()
                print(f"  failed {message_id}: {exc}")

        return BackfillReport(missing=len(missing), filled=filled, failed=failed)
    

async def run(dry_run: bool):
    try:
        report = await backfill(async_session_factory, get_llm(), dry_run)
    finally:
        await engine.dispose()

    print(f"{report.missing} messages had no embedding")
    if not dry_run:
        print(f"filled {report.filled}, failed {report.failed}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="only count, embed nothing"
    )
    args = parser.parse_args()
    asyncio.run(run(args.dry_run))

if __name__ == "__main__":
    main()