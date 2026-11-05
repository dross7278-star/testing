import json

from .client import ApiClient
from .simulator import FakeService, Item, VirtualClock


def main() -> None:
    clock = VirtualClock()
    pages = [
        [Item(index, f"item-{index}") for index in range(start, start + 100)]
        for start in range(0, 1_000, 100)
    ]
    service = FakeService(pages, clock)
    items = ApiClient(service).fetch_all()
    print(
        json.dumps(
            {
                "expected_items": 1_000,
                "returned_items": len(items),
                "requests": len(service.attempts),
                "virtual_seconds": round(clock.now, 6),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
