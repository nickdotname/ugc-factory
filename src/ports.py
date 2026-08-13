"""Injected sources of non-determinism: the clock and the random generator.

Responsibility: give the rest of ``src/`` a way to ask "what time is it" and
"pick one of these" without calling ``datetime.now()`` or ``random`` directly.

SPEC §2.2 requires determinism under a fixed seed and tests that do not depend
on wall-clock time. Every module that needs time or randomness takes a ``Clock``
or ``Rng`` as a constructor argument; the real implementations are wired up
exactly once, in ``cli.py``.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Sequence, TypeVar

T = TypeVar("T")


class Clock(ABC):
    """A source of the current time, always timezone-aware and in UTC."""

    @abstractmethod
    def now(self) -> datetime:
        """Return the current instant as a tz-aware UTC datetime."""


class SystemClock(Clock):
    """The real clock. The only thing in the codebase that reads wall time."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FrozenClock(Clock):
    """A clock pinned to a fixed instant, for tests and dry runs."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._instant = instant.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._instant

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._instant = self._instant + timedelta(seconds=seconds)


class Rng(ABC):
    """A source of randomness with the few operations the selector needs."""

    @abstractmethod
    def choice(self, items: Sequence[T]) -> T:
        """Pick one item uniformly."""

    @abstractmethod
    def weighted_choice(self, items: Sequence[T], weights: Sequence[float]) -> T:
        """Pick one item with probability proportional to its weight."""

    @abstractmethod
    def shuffled(self, items: Sequence[T]) -> list[T]:
        """Return a new shuffled list; never mutates the input."""


class SeededRng(Rng):
    """Deterministic RNG. Same seed plus same inputs gives the same picks.

    This is the only implementation — there is no "real" unseeded variant.
    Production seeds from the render date (see ``cli.py``), which keeps a given
    day's render reproducible while still varying day to day.
    """

    def __init__(self, seed: int) -> None:
        self._random = random.Random(seed)

    def choice(self, items: Sequence[T]) -> T:
        if not items:
            raise ValueError("choice() on an empty sequence")
        return self._random.choice(list(items))

    def weighted_choice(self, items: Sequence[T], weights: Sequence[float]) -> T:
        if not items:
            raise ValueError("weighted_choice() on an empty sequence")
        if len(items) != len(weights):
            raise ValueError(
                f"weighted_choice() got {len(items)} items but {len(weights)} weights"
            )
        if any(w < 0 for w in weights):
            raise ValueError("weighted_choice() got a negative weight")
        if sum(weights) <= 0:
            # All-zero weights would make random.choices raise; fall back to
            # uniform so an all-cold library still yields a pick.
            return self._random.choice(list(items))
        return self._random.choices(list(items), weights=list(weights), k=1)[0]

    def shuffled(self, items: Sequence[T]) -> list[T]:
        out = list(items)
        self._random.shuffle(out)
        return out
