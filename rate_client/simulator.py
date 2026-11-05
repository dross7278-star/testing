from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Item:
    id: int
    value: str


@dataclass(frozen=True)
class Page:
    items: tuple[Item, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class Attempt:
    time: float
    cursor: str | None
    status: int


class VirtualClock:
    """Advance simulated time without sleeping or touching the network."""

    def __init__(self) -> None:
        self.now = 0.0

    def sleep(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Sleep duration must be finite and non-negative")
        self.now += seconds


class ApiError(Exception):
    def __init__(self, status: int, retry_after: float | None = None) -> None:
        super().__init__(f"API returned HTTP {status}")
        self.status = status
        self.retry_after = retry_after


class SimulationLimitError(RuntimeError):
    """A safety guard, not a retriable HTTP error."""


class FakeService:
    def __init__(
        self,
        pages: Sequence[Sequence[Item]],
        clock: VirtualClock,
        *,
        requests_per_window: int = 100,
        window_seconds: float = 1.0,
        latency: float = 0.01,
        failures: Mapping[str | None, Sequence[int]] | None = None,
        request_budget: int = 1_000,
    ) -> None:
        if requests_per_window < 1 or request_budget < 1:
            raise ValueError("Request limits must be positive")
        if not math.isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("Window duration must be finite and positive")
        if not math.isfinite(latency) or latency < 0:
            raise ValueError("Latency must be finite and non-negative")
        self.clock = clock
        self.pages = tuple(tuple(page) for page in pages) or ((),)
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self.latency = latency
        self.request_budget = request_budget
        self.attempts: list[Attempt] = []
        self.requests_by_cursor: Counter[str | None] = Counter()
        self._admitted: deque[float] = deque()
        self._failures = {
            cursor: deque(statuses) for cursor, statuses in (failures or {}).items()
        }
        self._cursors = {
            f"page:{index}": index for index in range(1, len(self.pages))
        }

    def fetch_page(self, cursor: str | None) -> Page:
        if len(self.attempts) >= self.request_budget:
            raise SimulationLimitError("Simulator request budget exhausted")
        self.clock.sleep(self.latency)
        self.requests_by_cursor[cursor] += 1
        while self._admitted and (
            self.clock.now - self._admitted[0] >= self.window_seconds
        ):
            self._admitted.popleft()
        if len(self._admitted) >= self.requests_per_window:
            retry_after = self.window_seconds - (
                self.clock.now - self._admitted[0]
            )
            self.attempts.append(Attempt(self.clock.now, cursor, 429))
            raise ApiError(429, retry_after)
        self._admitted.append(self.clock.now)
        index = 0 if cursor is None else self._cursors.get(cursor)
        if index is None:
            self.attempts.append(Attempt(self.clock.now, cursor, 400))
            raise ApiError(400)
        failures = self._failures.get(cursor)
        if failures:
            status = failures.popleft()
            self.attempts.append(Attempt(self.clock.now, cursor, status))
            raise ApiError(status)
        self.attempts.append(Attempt(self.clock.now, cursor, 200))
        next_cursor = f"page:{index + 1}" if index + 1 < len(self.pages) else None
        return Page(self.pages[index], next_cursor)
