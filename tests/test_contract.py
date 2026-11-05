import unittest

from rate_client.client import ApiClient
from rate_client.simulator import ApiError, FakeService, Item, VirtualClock


class ClientContractTests(unittest.TestCase):
    def test_includes_terminal_page(self) -> None:
        service = FakeService([[Item(1, "a")]], VirtualClock())
        self.assertEqual(ApiClient(service).fetch_all(), [Item(1, "a")])

    def test_follows_cursor_through_empty_pages(self) -> None:
        service = FakeService([[Item(1, "a")], [], [Item(2, "b")]], VirtualClock())
        self.assertEqual(
            ApiClient(service).fetch_all(), [Item(1, "a"), Item(2, "b")]
        )
        self.assertEqual(len(service.attempts), 3)

    def test_includes_all_pages_in_service_order(self) -> None:
        service = FakeService(
            [[Item(3, "a")], [Item(1, "b")], [Item(2, "c")]], VirtualClock()
        )
        self.assertEqual(
            ApiClient(service).fetch_all(),
            [Item(3, "a"), Item(1, "b"), Item(2, "c")],
        )
        self.assertEqual(
            [attempt.cursor for attempt in service.attempts],
            [None, "page:1", "page:2"],
        )

    @unittest.expectedFailure
    def test_deduplicates_by_id_preserving_first_seen_order_and_value(self) -> None:
        service = FakeService(
            [[Item(2, "first"), Item(1, "a")], [Item(2, "changed"), Item(3, "b")], []],
            VirtualClock(),
        )
        self.assertEqual(
            ApiClient(service).fetch_all(),
            [Item(2, "first"), Item(1, "a"), Item(3, "b")],
        )

    @unittest.expectedFailure
    def test_respects_retry_after(self) -> None:
        clock = VirtualClock()
        service = FakeService(
            [[], []], clock, requests_per_window=1, window_seconds=5, latency=0
        )
        self.assertEqual(ApiClient(service).fetch_all(), [])
        self.assertEqual([attempt.status for attempt in service.attempts], [200, 429, 200])
        self.assertGreaterEqual(service.attempts[2].time, 5)

    @unittest.expectedFailure
    def test_retry_budget_resets_for_each_page(self) -> None:
        service = FakeService(
            [[], [], []],
            VirtualClock(),
            failures={None: [503, 503], "page:1": [502, 502], "page:2": [503, 503]},
        )
        self.assertEqual(ApiClient(service, max_attempts=3).fetch_all(), [])
        self.assertEqual(len(service.attempts), 9)

    @unittest.expectedFailure
    def test_transient_backoff_doubles_between_retries(self) -> None:
        service = FakeService(
            [[]], VirtualClock(), failures={None: [502, 503]}, latency=0
        )
        self.assertEqual(ApiClient(service).fetch_all(), [])
        self.assertEqual(len(service.attempts), 3)
        for attempt, expected_time in zip(service.attempts, (0, 0.1, 0.3), strict=True):
            self.assertAlmostEqual(attempt.time, expected_time)

    @unittest.expectedFailure
    def test_transient_backoff_is_capped(self) -> None:
        service = FakeService(
            [[]], VirtualClock(), failures={None: [503] * 5}, latency=0
        )
        self.assertEqual(ApiClient(service, max_attempts=6).fetch_all(), [])
        self.assertEqual(len(service.attempts), 6)
        for attempt, expected_time in zip(
            service.attempts, (0, 0.1, 0.3, 0.7, 1.5, 2.5), strict=True
        ):
            self.assertAlmostEqual(attempt.time, expected_time)

    @unittest.expectedFailure
    def test_permanent_error_is_not_retried(self) -> None:
        service = FakeService([[]], VirtualClock(), failures={None: [400] * 3})
        with self.assertRaises(ApiError) as caught:
            ApiClient(service).fetch_all()
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(len(service.attempts), 1)

    def test_results_do_not_leak_between_calls_or_through_returned_lists(self) -> None:
        service = FakeService([[Item(1, "a")], []], VirtualClock())
        client = ApiClient(service)
        first = client.fetch_all()
        first.append(Item(999, "caller mutation"))
        self.assertEqual(client.fetch_all(), [Item(1, "a")])

    def test_failed_call_does_not_contaminate_next_call(self) -> None:
        service = FakeService(
            [[Item(1, "a")], []],
            VirtualClock(),
            failures={"page:1": [503, 503, 503]},
        )
        client = ApiClient(service)
        with self.assertRaises(ApiError):
            client.fetch_all()
        self.assertEqual(client.fetch_all(), [Item(1, "a")])

    def test_repeated_calls_return_distinct_complete_lists(self) -> None:
        service = FakeService([[Item(1, "a")], [Item(2, "b")]], VirtualClock())
        client = ApiClient(service)
        first = client.fetch_all()
        second = client.fetch_all()
        self.assertIsNot(first, second)
        self.assertEqual(first, [Item(1, "a"), Item(2, "b")])
        self.assertEqual(second, first)
        second.clear()
        self.assertEqual(first, [Item(1, "a"), Item(2, "b")])
        self.assertEqual(client.fetch_all(), first)
        self.assertEqual(len(service.attempts), 6)

    def test_empty_calls_return_distinct_lists(self) -> None:
        client = ApiClient(FakeService([], VirtualClock()))
        first = client.fetch_all()
        second = client.fetch_all()
        self.assertIsNot(first, second)
        self.assertEqual(first, [])
        self.assertEqual(second, [])

    @unittest.expectedFailure
    def test_no_unnecessary_sleep_on_successful_requests(self) -> None:
        clock = VirtualClock()
        service = FakeService(
            [
                [Item(index, str(index)) for index in range(start, start + 100)]
                for start in range(0, 1_000, 100)
            ],
            clock,
        )
        result = ApiClient(service).fetch_all()
        self.assertLessEqual(clock.now, 0.15)
        self.assertEqual(len(service.attempts), 10)
        self.assertEqual([item.id for item in result], list(range(1_000)))
