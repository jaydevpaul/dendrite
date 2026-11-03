"""Handing work to the background worker."""

import logging
from uuid import UUID

from arq import ArqRedis

logger = logging.getLogger(__name__)

async def enqueue_embedding(queue: ArqRedis, message_id: UUID):
    """Ask the worker to embed this message. Never raises.

    By the time this runs the message is already saved, and a missing
    embedding only makes retrieval a little weaker. So if Redis is down the
    request still succeeds; the failure is logged and the backfill command
    picks the message up later.
    """
    try:
        await queue.enqueue_job('embed_message_job',message_id)
    except Exception:
        logger.exception("could not queue embedding for message %s",message_id)

        