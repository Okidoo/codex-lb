## Why

The dashboard weekly credits pace card currently excludes accounts whose
persisted status is `quota_exceeded` or `rate_limited`. A fully used weekly
account is therefore removed from the pool exactly when its zero remaining
credits should increase the pace gap and recovery warning.

## What Changes

- Count fresh weekly usage rows from `rate_limited` and `quota_exceeded`
  accounts in weekly pace totals and forecasts.
- Continue excluding paused, deactivated, missing, and stale accounts from the
  pace pool.
- Cover a fresh `quota_exceeded` account at 100% weekly usage in the dashboard
  projections integration test.

## Impact

- Modified capability: `frontend-architecture`
- Backend: dashboard weekly pace filtering
- Tests: dashboard projections weekly pace coverage
