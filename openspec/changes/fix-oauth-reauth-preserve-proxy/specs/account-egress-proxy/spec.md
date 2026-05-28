## MODIFIED Requirements

### Requirement: OAuth add-account with proxy validates before account activation

The service MUST handle account adds through the OAuth dashboard flow (browser,
manual-callback, or device-code) together with a SOCKS5 proxy configuration,
by performing the end-to-end proxy probe BEFORE inserting or
updating the account row. The OAuth attempt MUST signal "proxy expected" at
`POST /api/oauth/start` time via an `expect_proxy=true` flag and MUST include
the start-time proxy configuration on that start request. When that flag is
set, server-side OAuth bootstrap/token-exchange calls for that attempt MUST
use the start-time SOCKS5 proxy with the codex TLS profile.
Token-arrival sites MUST hold the acquired OAuth tokens in transient in-memory
state and MUST NOT persist the account until the operator submits a proxy
configuration via `POST /api/oauth/complete`.

When an OAuth attempt targets an existing account for re-authentication, the
service MUST persist the refreshed OAuth tokens into that existing account row
instead of applying generic add-account duplicate/copy behavior. The stored
account proxy configuration MUST be preserved. If that existing account has a
stored proxy, server-side OAuth calls for the re-authentication attempt MUST
use that stored proxy configuration.

This requirement covers codex-lb server-side OAuth calls, proxy probes, and
post-persistence account egress; the operator's own browser/device navigation
MUST NOT be treated as account activation or account traffic through codex-lb.
That completion-time proxy configuration MAY be a correction after a previous
probe failure, but it MUST still be probed before account persistence. A probe
failure MUST return 422 `proxy_probe_failed` with a typed reason and MUST NOT
persist the account. A successful probe MUST persist the account, the
completion-time proxy configuration, and the rotated OAuth tokens atomically,
and MUST invalidate the account's cached egress client before any post-add
usage refresh runs.

The held token state MUST be bounded by time and cleared when the operator
resets/closes the OAuth dialog, so abandoned OAuth attempts do not retain
authenticated state indefinitely. Closing the dashboard's OAuth dialog (which
calls `start_oauth` again or otherwise resets the OAuth state store) MUST
also drop the held tokens.

#### Scenario: Targeted re-authentication preserves the existing proxy
- **GIVEN** a deactivated account with a stored proxy configuration
- **AND** duplicate imports/adds are configured to create separate account rows
- **WHEN** the operator starts OAuth re-authentication for that account
- **AND** the upstream OAuth flow succeeds for the same account identity
- **THEN** the service updates the existing account row to active with the new tokens
- **AND** no duplicate account row is created
- **AND** the stored proxy configuration remains attached to the account
- **AND** server-side OAuth calls for that attempt use the stored proxy

#### Scenario: Targeted re-authentication rejects a different identity
- **GIVEN** a deactivated account selected for OAuth re-authentication
- **WHEN** the upstream OAuth flow returns credentials for a different
  ChatGPT account id or email
- **THEN** the service rejects the re-authentication
- **AND** the existing account row and proxy configuration are not overwritten
