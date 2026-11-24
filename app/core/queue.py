"""Handing work to the background worker."""

import logging
from uuid import UUID

from arq import ArqRedis

logger = logging.getLogger(__name__)

async def _enqueue(queue: ArqRedis,job:str, message_id: UUID):
    try:
        await queue.enqueue_job(job,message_id)
    except Exception:
        logger.exception("could not queue %s for message %s",job,message_id)

async def enqueue_message_jobs(queue:ArqRedis, message_id:UUID):
    """Ask the worker to embed and summarize this message."""

    await _enqueue(queue,"embed_message_job",message_id)
    await _enqueue(queue,"summarize_message_job",message_id)

