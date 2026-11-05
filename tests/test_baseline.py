import unittest

from rate_client.client import ApiClient
from rate_client.simulator import (
    ApiError,
    FakeService,
    SimulationLimitError,
    VirtualClock,
)


class BaselineTests(unittest.TestCase):
    def test_empty_dataset(self) -> None:
        service = FakeService([], VirtualClock())
        self.assertEqual(ApiClient(service).fetch_all(), [])
        self.assertEqual(len(service.attempts), 1)

    def test_retry_exhaustion_preserves_original_error(self) -> None:
        service = FakeService(
            [[]], VirtualClock(), failures={None: [503, 503, 503, 503]}
        )
        with self.assertRaises(ApiError) as caught:
            ApiClient(service, max_attempts=3).fetch_all()
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(len(service.attempts), 3)

    def test_invalid_retry_budget(self) -> None:
        with self.assertRaises(ValueError):
            ApiClient(FakeService([], VirtualClock()), max_attempts=0)

    def test_single_attempt_propagates_error_without_sleeping(self) -> None:
        clock = VirtualClock()
        service = FakeService([[]], clock, failures={None: [503]}, latency=0)
        with self.assertRaises(ApiError):
            ApiClient(service, max_attempts=1).fetch_all()
        self.assertEqual(len(service.attempts), 1)
        self.assertEqual(clock.now, 0)

    def test_simulation_limit_is_not_retried(self) -> None:
        service = FakeService([[], []], VirtualClock(), request_budget=1)
        with self.assertRaises(SimulationLimitError):
            ApiClient(service).fetch_all()
        self.assertEqual(len(service.attempts), 1)
