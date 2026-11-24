"""The background worker. It runs as its own process, beside the server:

    arq app.worker.WorkerSettings
"""

from uuid import UUID

from arq import Retry
from arq.connections import RedisSettings

from app.api.deps import get_llm
from app.core.config import settings
from app.core.db import async_session_factory,engine

from app.services.embedding import embed_message
from app.services.summary import summarize_message


async def startup(ctx):
    # One client for the worker's whole life, not a new one per job.
    ctx['llm']=get_llm()

async def shutdown(ctx):
    await engine.dispose()

async def embed_message_job(ctx,message_id:UUID):

    async with async_session_factory() as session:
        try:
            return await embed_message(session,ctx['llm'],message_id)
        except Exception as exc:
            raise Retry(defer=ctx["job_try"]*10) from exc

async def summarize_message_job(ctx, message_id: UUID):
    async with async_session_factory() as session:
        try:
            return await summarize_message(session, ctx["llm"], message_id)
        except Exception as exc:
            # arq only retries a job that raises Retry. Anything else marks it
            # failed for good, so a provider's bad minute, or a blank answer,
            # would cost the message its summary until the backfill ran.
            raise Retry(defer=ctx["job_try"] * 10) from exc

class WorkerSettings:
    functions=[embed_message_job,summarize_message_job]
    on_startup=startup
    on_shutdown=shutdown
    redis_settings=RedisSettings.from_dsn(settings.redis_url)
    max_tries = 3

