# Rate Client Lab

A small Python portfolio exercise: fix and optimize a deliberately broken
paginated API client. No credentials, external API, runtime dependencies, real
sleep, or network access are needed to run it.

**The client is now corrected and optimized.** The original intentionally buggy
starter is preserved in commit `1b72021` for comparison. The simulator remains
unchanged by the client fixes.

## Run

Python 3.12 or newer:

```console
python -m unittest discover -v
python -m rate_client
```

Run from the repository root. Installation is unnecessary.

The original suite had 12 passing tests and 11 expected failures. The completed
suite has **38 passing tests, zero expected failures, and zero skips** on Python
3.12 and 3.15. Every former expected-failure test is now an ordinary regression
test with its assertions preserved.

## Step-by-step fix notes

### 1. Include the terminal page

- **Bug:** checking `next_cursor` before collecting records discarded the last
  page, including every record in a single-page response.
- **Fix:** collect each successful page before deciding whether pagination ends.
  Continue using the returned opaque cursor, including through empty pages.
- **Verification:** single-page, ordered multi-page, and empty-middle-page tests.
- **History:** commit `3653ffd`.

### 2. Isolate results between calls

- **Bug:** an instance-level list accumulated records across requests and exposed
  shared mutable state to callers. A failed fetch also left partial results.
- **Fix:** create the result list inside `fetch_all`, so every invocation owns
  its results and failed invocations cannot retain partial data.
- **Verification:** caller mutation, failed-then-successful fetch, repeated-call
  identity, and empty-result identity tests.
- **History:** commit `42f34ab`.

### 3. Deduplicate without changing order or values

- **Bug:** appending every page directly allowed overlapping records to repeat.
- **Fix:** keep a local set of seen IDs and append only the first occurrence.
  The list preserves service order and the first value; the set gives expected
  constant-time membership checks, for O(n) total processing and O(u) result/
  deduplication storage for n records and u unique IDs.
- **Verification:** duplicates across pages, within the terminal page, ID zero,
  and a 20,000-record duplicate-heavy dataset fetched twice.

### 4. Retry only the allowed status codes

- **Bug:** catching every `ApiError` as retriable wasted requests on permanent
  errors and hid their immediate failure.
- **Fix:** retry only 429, 502, and 503. Re-raise all other API errors immediately.
  Catch no unrelated exception, so `SimulationLimitError` still propagates.
- **Verification:** 400, 401, 403, 404, 408, 500, 501, and 504 each fail after one
  request with no sleep; the simulator request-budget baseline remains passing.

### 5. Bound retries independently for each page

- **Bug:** failures counted across the entire fetch exhausted later pages'
  budgets even when previous pages had succeeded.
- **Fix:** reset failures and backoff after each successful page. Interpret
  `max_attempts` as all attempts for that page, including the initial request.
  Re-raise the final error before sleeping when the budget is exhausted.
  Reject non-integer, boolean, or non-positive budgets explicitly.
- **Verification:** each of three pages may use all three attempts; a later
  page can exhaust its own budget; the last status is preserved; a one-attempt
  budget never sleeps; mixed 503/429 failures share the same page budget.

### 6. Honor rate limits and use capped exponential backoff

- **Bug:** a fixed 0.1-second retry delay ignored `retry_after` and did not back
  off for repeated service failures.
- **Fix:** use the service's numeric `retry_after` seconds for 429 without
  applying the one-second backoff cap to that server-provided delay.
  Otherwise use 0.1, 0.2, 0.4, 0.8, 1.0, 1.0, ... seconds.
  Double the backoff after each retriable failure, capped at one second, without
  calculating arbitrarily large powers. Reset it on successful pages.
- **Verification:** exact attempt timestamps, the cap across 20 failures, reset
  between pages, a 20-second server delay, and repeated quota windows with
  nonzero request latency. Header-less scripted 429 errors use the same bounded
  backoff. Invalid supplied delay values are rejected by the virtual clock.

### 7. Remove unnecessary success-path waiting

- **Bug:** sleeping for one second after every successful page added ten seconds
  to a fetch that needed only 0.1 seconds of simulated request latency.
- **Fix:** remove that unconditional sleep. Wait only after retriable failures.
  This changes neither pagination order nor request count.
- **Verification:** the benchmark asserts all 1,000 ordered IDs, exactly ten
  requests, and a maximum of 0.15 virtual seconds. Actual time is 0.1 seconds,
  **101 times faster in simulated elapsed time** than the original starter.

### 8. Turn known failures into enforced regressions

- Reproduced all seven remaining failures without expected-failure decorators
  before implementing steps 3-7.
- Removed the decorators without weakening the assertions, and added eleven
  edge-case tests plus an invalid-delay test. Preserved all simulator and
  baseline behavior checks.
- Ran the full 38-test suite and benchmark on both supported CI runtimes.
- The existing [GitHub Actions workflow](.github/workflows/tests.yml) runs the
  same suite and benchmark on every push and pull request.

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
- If a scripted HTTP 429 has no `retry_after`, use the same capped backoff as
  502/503. Invalid numeric delays fail explicitly through the virtual clock.
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

All of these behaviors are covered by deterministic contract and baseline tests.
This is a simulator-backed client, not a production HTTP adapter: real HTTP
headers, network timeouts, and distributed quotas remain outside its scope.

## Deterministic performance goal

`python -m rate_client` fetches 1,000 records across ten pages. Each request costs
0.01 virtual seconds, and the quota admits 100 requests per one-second window.

| Metric | Buggy starter | Completed client | Required target |
| --- | ---: | ---: | ---: |
| Returned records | 900 | 1,000 | 1,000 |
| Requests | 10 | 10 | 10 |
| Virtual seconds | 10.1 | 0.1 | <= 0.15 |

The performance test asserts the time ceiling, request count, and exact ordered
IDs. Time is simulated, not wall-clock time; the benchmark measures unnecessary
waiting rather than Python CPU speed. Do not replace it with flaky real-time
thresholds.

## Repository map

- [client](rate_client/client.py): corrected pagination, deduplication, and retries.
- [simulator](rate_client/simulator.py): immutable pages, opaque cursors, rolling
  rate limits, scripted errors, request audit log, and a hard request budget.
- [contract tests](tests/test_contract.py): passing regressions and edge cases.
- [baseline tests](tests/test_baseline.py): behaviors that must remain working.
- [simulator tests](tests/test_simulator.py): fixture verification.
- [CI](.github/workflows/tests.yml): tests and benchmark on Python 3.12 and 3.15.

## Portfolio evidence

Compare the original starter commit against the current client, then run the two
commands above. The fix notes explain causes, implementation choices, and
regression evidence; Git history preserves the starter and incremental fixes.
No real HTTP adapter, async framework, database, or extra runtime dependency
was needed.
