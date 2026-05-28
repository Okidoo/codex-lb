## Why

The per-account token refresh jitter added in the current branch shifts
refresh eligibility in both directions around the configured interval.
With the default settings, an account that previously refreshed after 8
days can now be skipped until as late as 8 days + 18 hours.

That makes the configured `token_refresh_interval_days` stop behaving as
a maximum credential age. In a fleet, accounts near the old 8-day
boundary look like they are not getting refreshed, because the positive
half of the jitter window deliberately delays them.

## What Changes

- Treat `token_refresh_interval_days` as the hard maximum age.
- Keep deterministic per-account jitter, but apply it only as an
  early-refresh offset inside `[interval - jitter, interval]`.
- Add regression coverage proving all accounts refresh once they pass the
  configured interval, regardless of jitter.
- Update the outbound HTTP client spec to require early-only jitter.

## Impact

- Accounts are still spread across the configured jitter window, reducing
  clustered refreshes.
- No account is delayed beyond the configured refresh interval.
- No API, database, or configuration shape changes.
