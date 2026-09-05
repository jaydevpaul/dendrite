"""The rule that decides how far fidelity drops per ancestor level.

Hierarchical decay is a family, not one algorithm, so the rule lives behind its
own interface and the strategy asks it rather than deciding for itself. One
implementation ships today; a token-budget or exponential version is a new
class here and no change anywhere else.
"""
from collections.abc import Sequence
from dataclasses import dataclass

from app.context.base import Fidelity
from app.services.ancestors import AncestorStep

@dataclass(frozen=True)
class TieredDecay:

    full_depth: int = 3

    def __post_init__(self):
        if self.full_depth < 0:
            raise ValueError("full_depth cannot be negative")

    def assign(self, steps: Sequence[AncestorStep]) -> list[Fidelity]:
        return [
            "full" if step.depth<=self.full_depth else "summary"
            for step in steps
        ]

   