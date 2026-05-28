## MODIFIED Requirements

### Requirement: Per-account token refresh jitter

The token refresh schedule MUST apply a deterministic per-account
early-refresh offset to the configured refresh interval so that accounts
onboarded on the same day do not refresh at the same moment. The offset
MUST be derived from `account_id` only — not from `last_refresh` — so a
given account always lands at the same point inside its window. The
offset MUST be in the range
`[0, account_token_refresh_jitter_hours]`.

The configured `token_refresh_interval_days` value MUST remain the hard
maximum token age: jitter MAY make an account refresh earlier than that
interval, but MUST NOT delay an account past it.

When `account_id` is not provided to the schedule check, the service
MUST fall back to the un-jittered `token_refresh_interval_days`
behavior.

#### Scenario: Same account always lands at the same point in its window
- **WHEN** the refresh schedule check is evaluated twice for the same
  `account_id` with the same `last_refresh`
- **THEN** both calls observe the same effective threshold

#### Scenario: Distinct accounts get distinct offsets
- **WHEN** the refresh schedule check is evaluated for two different
  `account_id`s with the same `last_refresh`
- **THEN** the two effective thresholds differ

#### Scenario: Offset is bounded by the configured early-refresh window
- **WHEN** `account_token_refresh_jitter_hours` is `H`
- **THEN** every per-account offset MUST be in `[0, H * 3600]` seconds

#### Scenario: Configured interval remains the maximum refresh age
- **WHEN** an account's `last_refresh` is older than
  `token_refresh_interval_days`
- **THEN** the refresh schedule check MUST return true regardless of that
  account's jitter offset
