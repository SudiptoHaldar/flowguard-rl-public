"""Polynomial penalty functions for circuits.

Coefficient convention (project-wide, established by ``config/example_circuit.yaml``):
ascending by degree, **degree-1 first** — ``[1, 2, 3]`` means ``v + 2v^2 + 3v^3``. The
constant term is implicitly zero, so every penalty function satisfies ``f(0) == 0``.
Coefficients must be finite and >= 0 with at least one > 0, which guarantees penalties
are non-negative and non-decreasing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Polynomial:
    coefficients: tuple

    def __post_init__(self):
        coefficients = tuple(self.coefficients)
        object.__setattr__(self, "coefficients", coefficients)
        if not coefficients:
            raise ValueError("Polynomial requires at least one coefficient")
        for c in coefficients:
            if isinstance(c, bool) or not isinstance(c, (int, float)):
                raise ValueError(f"Polynomial coefficients must be numbers, got {c!r}")
            if not math.isfinite(c):
                raise ValueError(f"Polynomial coefficients must be finite, got {c!r}")
            if c < 0:
                raise ValueError(f"Polynomial coefficients must be >= 0, got {c!r}")
        if not any(c > 0 for c in coefficients):
            raise ValueError("Polynomial requires at least one coefficient > 0")

    @classmethod
    def from_list(cls, coefficients) -> "Polynomial":
        return cls(tuple(coefficients))

    @property
    def degree(self) -> int:
        """Nominal degree: the length of the coefficient list (degree-1-first)."""
        return len(self.coefficients)

    def evaluate(self, v) -> float:
        # Horner with a trailing multiply by v (no constant term -> f(0) == 0).
        result = 0.0
        for c in reversed(self.coefficients):
            result = (result + c) * v
        return float(result)

    def as_list(self) -> list:
        return list(self.coefficients)
