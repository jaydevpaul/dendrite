from typing import Literal,get_args

from sqlalchemy.dialects.postgresql import UUID as PG_UUID

UUIDType = PG_UUID(as_uuid=True)

# The Five strategies
AnyStrategy = Literal[
    "FullInheritance",
    "ParentOnly",
    "SpanOnly",
    "HierarchicalDecay",
    "HierarchicalDecayWithRetrieval",
]
# SpanOnly is branch-only - never a conversation default.
NonSpanStrategy = Literal[
    "FullInheritance",
    "ParentOnly",
    "HierarchicalDecay",
    "HierarchicalDecayWithRetrieval",
]


ALL_STRATEGIES = get_args(AnyStrategy)

NON_SPAN_STRATEGIES = get_args(NonSpanStrategy)

if set(NON_SPAN_STRATEGIES) != set(ALL_STRATEGIES) - {"SpanOnly"}:
    raise RuntimeError("Strategy list drift: NonSpanStrategy is out of sync with AnyStrategy")

DEFAULT_STRATEGY: NonSpanStrategy = "HierarchicalDecayWithRetrieval"




def _sql_string_list(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


ALL_STRATEGIES_SQL = _sql_string_list(ALL_STRATEGIES)
NON_SPAN_STRATEGIES_SQL = _sql_string_list(NON_SPAN_STRATEGIES)
