"""Ancestor-scoped vector retrieval.

Every embedding in the system shares one table, so isolation is a property of
this query rather than of the schema. The candidate ids keep the search inside
the branch the user is on, and the model filter keeps it inside one vector
space. Drop either and nothing fails - the search just quietly gets wider.
"""
from uuid import UUID
from math import ceil

from collections.abc import Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.models.message_embedding import MessageEmbedding


def promotion_count(n_candidates: int, fraction:float, max_promotions: int):
    """How many summarized levels get their full text back."""

    return min(ceil(fraction*n_candidates),max_promotions)

async def rank_ancestors_by_similarity(
    session:AsyncSession,
    candidate_ids: Sequence[UUID],
    query_vector: Sequence[float],
    model : str         
):
    """The candidates that have a vector, nearest to the query first"""

    ids = list(candidate_ids)

    if not ids:
        return []

    distance = MessageEmbedding.embedding.cosine_distance(list(query_vector))

    result = await session.execute(
        select(MessageEmbedding.message_id,distance.label("distance"))
        .where(
            MessageEmbedding.message_id.in_(ids),
            MessageEmbedding.model_used == model,
        )
        .distinct(MessageEmbedding.message_id)
        .order_by(
            MessageEmbedding.message_id,
            MessageEmbedding.created_at.desc(),
            MessageEmbedding.id.desc()
        )
    )

    position = {message_id: index for index, message_id in enumerate(ids)}
    ranked = sorted(
        result.all(), key=lambda row: (row.distance, position[row.message_id])
    )

    return [row.message_id for row in ranked]
