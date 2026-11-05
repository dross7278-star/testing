import unittest
from unittest.mock import patch

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

    def test_deduplicates_by_id_preserving_first_seen_order_and_value(self) -> None:
        service = FakeService(
            [[Item(2, "first"), Item(1, "a")], [Item(2, "changed"), Item(3, "b")], []],
            VirtualClock(),
        )
        self.assertEqual(
            ApiClient(service).fetch_all(),
            [Item(2, "first"), Item(1, "a"), Item(3, "b")],
        )

    def test_respects_retry_after(self) -> None:
        clock = VirtualClock()
        service = FakeService(
            [[], []], clock, requests_per_window=1, window_seconds=5, latency=0
        )
        self.assertEqual(ApiClient(service).fetch_all(), [])
        self.assertEqual([attempt.status for attempt in service.attempts], [200, 429, 200])
        self.assertGreaterEqual(service.attempts[2].time, 5)

    def test_retry_budget_resets_for_each_page(self) -> None:
        service = FakeService(
            [[], [], []],
            VirtualClock(),
            failures={None: [503, 503], "page:1": [502, 502], "page:2": [503, 503]},
        )
        self.assertEqual(ApiClient(service, max_attempts=3).fetch_all(), [])
        self.assertEqual(len(service.attempts), 9)

    def test_transient_backoff_doubles_between_retries(self) -> None:
        service = FakeService(
            [[]], VirtualClock(), failures={None: [502, 503]}, latency=0
        )
        self.assertEqual(ApiClient(service).fetch_all(), [])
        self.assertEqual(len(service.attempts), 3)
        for attempt, expected_time in zip(service.attempts, (0, 0.1, 0.3), strict=True):
            self.assertAlmostEqual(attempt.time, expected_time)

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

    def test_deduplicates_within_terminal_page_including_zero_id(self) -> None:
        service = FakeService(
            [[Item(0, "first"), Item(1, "a"), Item(0, "changed")]], VirtualClock()
        )
        self.assertEqual(
            ApiClient(service).fetch_all(), [Item(0, "first"), Item(1, "a")]
        )

    def test_duplicate_heavy_dataset_preserves_order_on_repeated_calls(self) -> None:
        expected = [Item(index, str(index)) for index in range(999, -1, -1)]
        service = FakeService([expected * 10, expected * 10], VirtualClock())
        client = ApiClient(service)
        self.assertEqual(client.fetch_all(), expected)
        self.assertEqual(client.fetch_all(), expected)
        self.assertEqual(len(service.attempts), 4)

    def test_other_status_codes_propagate_without_sleep_or_retry(self) -> None:
        for status in (400, 401, 403, 404, 408, 500, 501, 504):
            with self.subTest(status=status):
                clock = VirtualClock()
                service = FakeService(
                    [[]], clock, failures={None: [status]}, latency=0
                )
                with self.assertRaises(ApiError) as caught:
                    ApiClient(service).fetch_all()
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(len(service.attempts), 1)
                self.assertEqual(clock.now, 0)

    def test_later_page_exhaustion_preserves_final_error_and_stops_waiting(self) -> None:
        clock = VirtualClock()
        service = FakeService(
            [[Item(1, "a")], []],
            clock,
            failures={None: [503, 503], "page:1": [502, 503, 502]},
            latency=0,
        )
        with self.assertRaises(ApiError) as caught:
            ApiClient(service).fetch_all()
        self.assertEqual(caught.exception.status, 502)
        self.assertEqual(service.requests_by_cursor[None], 3)
        self.assertEqual(service.requests_by_cursor["page:1"], 3)
        self.assertAlmostEqual(clock.now, 0.6)

    def test_backoff_resets_on_next_page(self) -> None:
        service = FakeService(
            [[], []],
            VirtualClock(),
            failures={None: [503, 502], "page:1": [503]},
            latency=0,
        )
        self.assertEqual(ApiClient(service).fetch_all(), [])
        self.assertEqual(len(service.attempts), 5)
        for attempt, expected_time in zip(
            service.attempts, (0, 0.1, 0.3, 0.3, 0.4), strict=True
        ):
            self.assertAlmostEqual(attempt.time, expected_time)

    def test_backoff_remains_capped_across_many_retries(self) -> None:
        service = FakeService(
            [[]], VirtualClock(), failures={None: [503] * 20}, latency=0
        )
        self.assertEqual(ApiClient(service, max_attempts=21).fetch_all(), [])
        self.assertEqual(len(service.attempts), 21)
        self.assertAlmostEqual(service.clock.now, 17.5)

    def test_retry_after_is_not_capped_by_transient_backoff(self) -> None:
        service = FakeService(
            [[], []],
            VirtualClock(),
            requests_per_window=1,
            window_seconds=20,
            latency=0,
        )
        self.assertEqual(ApiClient(service).fetch_all(), [])
        self.assertEqual([attempt.time for attempt in service.attempts], [0, 0, 20])
        self.assertEqual(service.clock.now, 20)

    def test_rate_limit_exhaustion_propagates_without_final_sleep(self) -> None:
        clock = VirtualClock()
        service = FakeService(
            [[], []], clock, requests_per_window=1, window_seconds=5, latency=0
        )
        with self.assertRaises(ApiError) as caught:
            ApiClient(service, max_attempts=1).fetch_all()
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(caught.exception.retry_after, 5)
        self.assertEqual(len(service.attempts), 2)
        self.assertEqual(clock.now, 0)

    def test_repeated_rate_limits_with_nonzero_latency(self) -> None:
        clock = VirtualClock()
        expected = [Item(index, str(index)) for index in range(4)]
        service = FakeService(
            [[item] for item in expected],
            clock,
            requests_per_window=1,
            window_seconds=1,
            latency=0.125,
        )
        self.assertEqual(ApiClient(service).fetch_all(), expected)
        self.assertEqual(
            [attempt.status for attempt in service.attempts],
            [200, 429, 200, 429, 200, 429, 200],
        )
        self.assertEqual(clock.now, 3.5)

    def test_rate_limit_without_retry_after_uses_bounded_backoff(self) -> None:
        service = FakeService(
            [[]], VirtualClock(), failures={None: [429, 429]}, latency=0
        )
        self.assertEqual(ApiClient(service).fetch_all(), [])
        self.assertEqual(len(service.attempts), 3)
        self.assertAlmostEqual(service.clock.now, 0.3)

    def test_mixed_transient_error_and_rate_limit_share_page_budget(self) -> None:
        clock = VirtualClock()
        service = FakeService(
            [[]],
            clock,
            failures={None: [503]},
            requests_per_window=1,
            window_seconds=1,
            latency=0,
        )
        self.assertEqual(ApiClient(service).fetch_all(), [])
        self.assertEqual([attempt.status for attempt in service.attempts], [503, 429, 200])
        self.assertEqual(clock.now, 1)

    def test_invalid_retry_after_fails_explicitly_without_retrying(self) -> None:
        for delay in (-1, float("nan"), float("inf")):
            with self.subTest(delay=delay):
                clock = VirtualClock()
                service = FakeService([[]], clock)
                error = ApiError(429, delay)
                with patch.object(service, "fetch_page", side_effect=error) as fetch:
                    with self.assertRaises(ValueError) as caught:
                        ApiClient(service).fetch_all()
                    self.assertIs(caught.exception.__context__, error)
                    fetch.assert_called_once_with(None)
                self.assertEqual(clock.now, 0)
