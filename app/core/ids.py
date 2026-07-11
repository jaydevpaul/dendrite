from uuid6 import uuid7 as _uuid7


def uuid7():
    """Single call site for the app's PK generation strategy (UUID v7)."""
    return _uuid7()
