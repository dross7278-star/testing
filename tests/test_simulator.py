import unittest

from rate_client.simulator import (
    ApiError,
    FakeService,
    Item,
    SimulationLimitError,
    VirtualClock,
)


class SimulatorTests(unittest.TestCase):
    def test_opaque_pagination_including_empty_middle_page(self) -> None:
        service = FakeService([[Item(1, "a")], [], [Item(2, "b")]], VirtualClock())
        first = service.fetch_page(None)
        middle = service.fetch_page(first.next_cursor)
        last = service.fetch_page(middle.next_cursor)
        self.assertEqual(first.items, (Item(1, "a"),))
        self.assertEqual(middle.items, ())
        self.assertEqual(last.items, (Item(2, "b"),))
        self.assertIsNone(last.next_cursor)

    def test_retry_after_allows_progress_at_exact_window_boundary(self) -> None:
        clock = VirtualClock()
        service = FakeService(
            [[]], clock, requests_per_window=1, window_seconds=2, latency=0
        )
        service.fetch_page(None)
        with self.assertRaises(ApiError) as caught:
            service.fetch_page(None)
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(caught.exception.retry_after, 2)
        clock.sleep(2)
        self.assertEqual(service.fetch_page(None).items, ())
        self.assertEqual([attempt.status for attempt in service.attempts], [200, 429, 200])

    def test_scripted_errors_are_consumed_once(self) -> None:
        service = FakeService([[]], VirtualClock(), failures={None: [503, 502]})
        for status in (503, 502):
            with self.assertRaises(ApiError) as caught:
                service.fetch_page(None)
            self.assertEqual(caught.exception.status, status)
        self.assertEqual(service.fetch_page(None).items, ())
        self.assertEqual(service.requests_by_cursor[None], 3)

    def test_invalid_cursor_is_explicit_permanent_error(self) -> None:
        service = FakeService([[]], VirtualClock())
        with self.assertRaises(ApiError) as caught:
            service.fetch_page("invalid")
        self.assertEqual(caught.exception.status, 400)

    def test_request_budget_bounds_broken_clients(self) -> None:
        service = FakeService([[]], VirtualClock(), request_budget=1)
        service.fetch_page(None)
        with self.assertRaises(SimulationLimitError):
            service.fetch_page(None)
        self.assertEqual(len(service.attempts), 1)

    def test_invalid_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FakeService([[]], VirtualClock(), requests_per_window=0)
        with self.assertRaises(ValueError):
            FakeService([[]], VirtualClock(), request_budget=0)
        for window in (0, float("nan")):
            with self.subTest(window=window), self.assertRaises(ValueError):
                FakeService([[]], VirtualClock(), window_seconds=window)
        for latency in (-1, float("inf")):
            with self.subTest(latency=latency), self.assertRaises(ValueError):
                FakeService([[]], VirtualClock(), latency=latency)

    def test_clock_rejects_invalid_durations(self) -> None:
        clock = VirtualClock()
        for seconds in (-1, float("inf"), float("nan")):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                clock.sleep(seconds)
        self.assertEqual(clock.now, 0)
