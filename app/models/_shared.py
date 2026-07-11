from sqlalchemy.dialects.postgresql import UUID as PG_UUID

UUIDType = PG_UUID(as_uuid=True)

ALL_STRATEGIES = (
    "FullInheritance",
    "ParentOnly",
    "SpanOnly",
    "HierarchicalDecay",
    "HierarchicalDecayWithRetrieval",
)
NON_SPAN_STRATEGIES = tuple(s for s in ALL_STRATEGIES if s != "SpanOnly")


def _sql_string_list(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


ALL_STRATEGIES_SQL = _sql_string_list(ALL_STRATEGIES)
NON_SPAN_STRATEGIES_SQL = _sql_string_list(NON_SPAN_STRATEGIES)
