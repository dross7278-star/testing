from .simulator import ApiError, FakeService, Item


class ApiClient:
    """Fetch unique items with bounded, deterministic per-page retries."""

    def __init__(self, service: FakeService, *, max_attempts: int = 3) -> None:
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts < 1
        ):
            raise ValueError("max_attempts must be a positive integer")
        self.service = service
        self.max_attempts = max_attempts

    def fetch_all(self) -> list[Item]:
        items: list[Item] = []
        seen_ids: set[int] = set()
        cursor: str | None = None
        failures = 0
        backoff = 0.1
        while True:
            try:
                page = self.service.fetch_page(cursor)
            except ApiError as error:
                failures += 1
                if error.status not in (429, 502, 503) or failures >= self.max_attempts:
                    raise
                delay = (
                    error.retry_after
                    if error.status == 429 and error.retry_after is not None
                    else backoff
                )
                self.service.clock.sleep(delay)
                backoff = min(backoff * 2, 1.0)
                continue
            failures = 0
            backoff = 0.1
            for item in page.items:
                if item.id not in seen_ids:
                    seen_ids.add(item.id)
                    items.append(item)
            if page.next_cursor is None:
                return items
            cursor = page.next_cursor
