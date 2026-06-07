## 1. Spec

- [x] 1.1 Clarify that exhausted but fresh weekly accounts remain in pace totals.

## 2. Implementation

- [x] 2.1 Include `rate_limited` and `quota_exceeded` accounts in backend weekly pace when their weekly usage data is fresh and complete.
- [x] 2.2 Keep paused, deactivated, missing, and stale accounts excluded from weekly pace.

## 3. Verification

- [x] 3.1 Add integration coverage for a fresh `quota_exceeded` account at 100% weekly usage.
- [x] 3.2 Run targeted dashboard tests, ruff, and OpenSpec validation.
