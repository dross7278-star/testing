# Rate Client Lab

A small Python portfolio exercise: fix and optimize a deliberately broken
paginated API client. No credentials, external API, runtime dependencies, real
sleep, or network access are needed to run it.

**This is a work-in-progress exercise, not a completed solution.** The simulator is the
test fixture; contributors should fix the client without weakening that fixture
or the acceptance assertions.

## Run

Python 3.12 or newer:

```console
python -m unittest discover -v
python -m rate_client
```

Run from the repository root. Installation is unnecessary.

The initial suite has 12 passing fixture/baseline tests and 11 explicitly marked
expected failures. Expected failures are known bugs, **not proof of correctness**.
As each bug is fixed, remove its `@unittest.expectedFailure` decorator. An
unexpected success makes unittest fail until that marker is removed.

### Verified progress

The original buggy starter is preserved in the first Git commit.

Step 1 fixes terminal-page loss by collecting each page before checking its
continuation cursor. Single-page, multi-page, and empty-intermediate-page
regressions now pass. The current suite has 15 passing tests and 9 expected
failures. The benchmark returns all 1,000 records with 10 requests, but still
takes 10.1 virtual seconds; retry, state isolation, deduplication, and performance
work remain intentionally unfinished.

Run just the contributor contract:

```console
python -m unittest tests.test_contract -v
```

## Target behavior

- Follow opaque `next_cursor` values until `None`. Include the terminal page,
  and do not stop on an empty intermediate page.
- Return unique records by ID in first-seen order; the first value wins.
- Retry only HTTP 429, 502, and 503. Propagate other errors immediately.
- Honor the simulator's numeric `retry_after` seconds for HTTP 429.
- For 502/503, use deterministic capped exponential backoff:
  `min(0.1 * 2 ** (retry_number - 1), 1.0)` seconds. The first retry is number 1.
- Interpret `max_attempts` as total attempts **per page**, including the first
  request. Reset the budget after a successful page; preserve the final error
  when exhausted. Never retry `SimulationLimitError`.
- Each call owns its result list. Caller mutation and partial failed fetches
  must not affect future calls.
- Never sleep after a successful response unless required by a future request's
  rate-limit response. Deduplication should be linear in the number of records,
  using a set rather than repeated list scans.

The supplied contract covers the central regressions but is not exhaustive.
Add coverage for additional permanent status codes, retry exhaustion on later
pages, backoff reset between pages, duplicate-heavy datasets, and quota boundaries
with nonzero request latency.

## Deterministic performance goal

`python -m rate_client` fetches 1,000 records across ten pages. Each request costs
0.01 virtual seconds, and the quota admits 100 requests per one-second window.

| Metric | Buggy starter | Required solution |
| --- | ---: | ---: |
| Returned records | 900 | 1,000 |
| Requests | 10 | 10 |
| Virtual seconds | 10.1 | <= 0.15 |

The performance test asserts the time ceiling, request count, and exact ordered
IDs. Time is simulated, not wall-clock time; the benchmark measures unnecessary
waiting rather than Python CPU speed. Do not replace it with flaky real-time
thresholds.

## Repository map

- [client](rate_client/client.py): intentionally flawed contributor surface.
- [simulator](rate_client/simulator.py): immutable pages, opaque cursors, rolling
  rate limits, scripted errors, request audit log, and a hard request budget.
- [contract tests](tests/test_contract.py): expected-failure regression cases.
- [baseline tests](tests/test_baseline.py): behaviors that must remain working.
- [simulator tests](tests/test_simulator.py): fixture verification.
- [CI](.github/workflows/tests.yml): tests and benchmark on Python 3.12 and 3.15.

## Suggested contribution sequence

1. Reproduce a contract failure and explain its root cause.
2. Fix pagination and isolate per-call state.
3. Add deduplication without changing order or first-seen values.
4. Refactor retry handling: status selection, per-page budget, and timing.
5. Remove unnecessary waiting and meet the measured performance target.
6. Add missing edge-case tests and remove every expected-failure marker.

A finished contribution must have zero expected failures, zero unexpected
successes, all assertions passing, and the benchmark meeting every target.
Include before/after output and a short explanation of correctness and tradeoffs
in the pull request. Keep changes scoped; no real HTTP adapter, async framework,
database, or additional dependencies are required.
