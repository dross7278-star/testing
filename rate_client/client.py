from .simulator import ApiError, FakeService, Item


class ApiClient:
    """Intentionally buggy starter. The contract tests define the target behavior."""

    def __init__(self, service: FakeService, *, max_attempts: int = 3) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.service = service
        self.max_attempts = max_attempts
        self._items: list[Item] = []

    def fetch_all(self) -> list[Item]:
        cursor: str | None = None
        failures = 0
        while True:
            try:
                page = self.service.fetch_page(cursor)
            except ApiError:
                failures += 1
                if failures >= self.max_attempts:
                    raise
                self.service.clock.sleep(0.1)
                continue
            self.service.clock.sleep(1.0)
            self._items.extend(page.items)
            if page.next_cursor is None:
                return self._items
            cursor = page.next_cursor
