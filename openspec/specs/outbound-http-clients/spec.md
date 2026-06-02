# outbound-http-clients Specification

## Purpose

Define outbound HTTP client behavior so upstream OAuth and API calls use stable headers, personas, and proxy handling.
## Requirements
### Requirement: OAuth authorize requests use a configurable originator persona
Browser OAuth authorize requests MUST include an `originator` query parameter. The service MUST default that parameter to `codex_chatgpt_desktop` and MUST let operators override it through configuration when they need a different first-party Codex persona.

#### Scenario: default OAuth authorize originator uses the Desktop persona
- **WHEN** the operator does not configure an override
- **THEN** the browser OAuth authorize URL includes `originator=codex_chatgpt_desktop`

#### Scenario: configured OAuth authorize originator falls back to the CLI persona
- **WHEN** the operator configures the OAuth authorize originator as `codex_cli_rs`
- **THEN** the browser OAuth authorize URL includes `originator=codex_cli_rs`

### Requirement: Browser OAuth redirect URI uses the registered callback

Browser OAuth start MUST use the configured `oauth_redirect_uri` unchanged
for the authorize `redirect_uri` and response `callbackUrl`. The token
exchange for that OAuth attempt MUST reuse the same redirect URI. The
dashboard request host MUST NOT rewrite the OAuth redirect URI.

#### Scenario: remote dashboard host does not rewrite browser OAuth callback
- **WHEN** a browser OAuth flow starts from a dashboard request whose host is
  `dashboard.example.test:2455`
- **AND** `oauth_redirect_uri` is `http://localhost:1455/auth/callback`
- **THEN** the authorize URL uses
  `redirect_uri=http://localhost:1455/auth/callback`
- **AND** the start response includes that same callback URL
- **AND** the authorization-code token exchange uses that same redirect URI

### Requirement: Account-bound outbound calls use the per-account egress client

Account-bound calls MUST route every outbound HTTP or WebSocket call made
on behalf of an account with a SOCKS5 proxy configured through that proxy.
When an account has no proxy configured, account-bound calls MUST
use a dedicated per-account direct egress client and MUST NOT share TCP /
TLS connections with other accounts.

The following call sites are considered "account-bound" and MUST honor this
rule:

- OAuth token refresh
- Codex `responses` HTTP path
- Codex `responses` WebSocket handshake and transport
- Account model fetcher
- Account usage fetcher
- Account-scoped file uploads/downloads

The following call sites are considered "non-account" and MUST continue to
use the shared global client unchanged:

- GitHub release / version check
- Dashboard-internal HTTP calls
- The OAuth login bootstrap flow that runs before any account exists

#### Scenario: Account with a configured proxy egresses through the proxy
- **WHEN** the account has `proxy_host` set
- **AND** the service performs an OAuth token refresh, a Codex `responses`
  HTTP request, a Codex `responses` WebSocket handshake, a model/usage
  fetch, or a files call for that account
- **THEN** the underlying `aiohttp.ClientSession` MUST be backed by a
  `ProxyConnector` whose proxy host, port, credentials, and DNS mode match
  the stored proxy configuration

#### Scenario: Account without a proxy uses dedicated direct egress
- **WHEN** the account has no `proxy_host`
- **AND** the service performs any account-bound outbound call
- **THEN** the call MUST construct or reuse the account's dedicated direct
  outbound client
- **AND** the call MUST NOT use the shared global outbound client

#### Scenario: Non-account outbound calls keep using the shared global client
- **WHEN** the service performs the GitHub release check, a dashboard-
  internal HTTP call, or the OAuth login bootstrap flow
- **THEN** the call MUST use the shared global outbound client regardless
  of any account proxy configuration

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

### Requirement: Outbound calls strip device and installation identifier headers

Outbound calls MUST strip every header in the device-identifier deny
set before forwarding to upstream. The deny set covers, at minimum:
`oai-device-id`, `oai-did`, `x-oai-device-id`, `x-openai-device-id`,
`oai-installation-id`, `x-oai-installation-id`, and
`x-openai-installation-id`. Header name matching MUST be
case-insensitive.

The deny set MUST be enforced in both filtering paths: the broad
forward path used by Codex `responses` HTTP and WebSocket, and the
explicit allow-list paths used by `/files` and `/transcribe` (even
when an entry would otherwise match the `x-openai-` / `x-codex-`
allow-list prefix).

#### Scenario: oai-device-id is stripped from a /responses request
- **WHEN** a Codex client sends `oai-device-id: device-abc` to the
  proxy
- **THEN** the upstream `/responses` HTTP request MUST NOT include
  `oai-device-id`

#### Scenario: x-openai-device-id is stripped from a /files request
- **WHEN** a Codex client sends `x-openai-device-id: device-abc` to
  the proxy
- **THEN** the upstream `/files` request MUST NOT include the header,
  even though the `x-openai-` prefix is otherwise allow-listed

#### Scenario: Header name matching is case-insensitive
- **WHEN** the inbound header is named `Oai-Device-Id`,
  `OAI-DEVICE-ID`, or any other case variant
- **THEN** the header MUST be stripped on the same code path as
  `oai-device-id`

### Requirement: Upstream websocket handshakes auto-detect standard proxy environment variables

When operators don't explicitly configure `upstream_websocket_trust_env`, upstream websocket handshakes MUST honor standard outbound proxy environment variables before connecting directly.
Explicit configuration MUST still override auto-detection.

#### Scenario: secure websocket handshakes honor scheme-compatible env proxies by default

- **WHEN** an upstream websocket URL uses the `wss://` scheme
- **AND** `wss_proxy`, `socks_proxy`, `https_proxy`, or `all_proxy` is set
- **AND** `upstream_websocket_trust_env` is not explicitly configured
- **THEN** upstream websocket handshakes use the configured proxy instead of bypassing it

#### Scenario: plain websocket handshakes honor scheme-compatible env proxies by default

- **WHEN** an upstream websocket URL uses the `ws://` scheme
- **AND** `ws_proxy`, `socks_proxy`, `https_proxy`, `http_proxy`, or `all_proxy` is set
- **AND** `upstream_websocket_trust_env` is not explicitly configured
- **THEN** upstream websocket handshakes use the configured proxy instead of bypassing it

#### Scenario: ws handshakes preserve HTTPS proxy fallback

- **WHEN** an upstream websocket URL uses the `ws://` scheme
- **AND** `https_proxy` is set without a `ws_proxy` or `http_proxy` override
- **THEN** the upstream websocket handshake uses the `https_proxy` value before falling back to `all_proxy`

#### Scenario: explicit direct-connect override bypasses env proxies

- **WHEN** `upstream_websocket_trust_env=false`
- **AND** standard outbound proxy environment variables are set
- **THEN** upstream websocket handshakes connect directly without using those proxies

### Requirement: Runtime version status checks latest GitHub release

The service SHALL expose a dashboard-auth protected runtime version status API that reports the running codex-lb version, the latest known GitHub release version when available, whether an update is available, and the time of the latest lookup attempt. The lookup MUST be cached in-process to avoid per-request GitHub traffic, and lookup failures MUST NOT cause the API to fail.

#### Scenario: Latest release is newer than current version

- **WHEN** the running version is `1.19.0`
- **AND** the GitHub latest release tag is `v1.20.0`
- **THEN** the runtime version status reports `currentVersion: "1.19.0"`, `latestVersion: "1.20.0"`, and `updateAvailable: true`

#### Scenario: GitHub lookup fails

- **WHEN** the GitHub latest release lookup fails
- **THEN** the runtime version status API still returns the current version
- **AND** `updateAvailable` is `false`

### Requirement: Model refresh recovers from shared HTTP client transport failures

When the model registry refresh path fails before receiving an upstream HTTP response because of a transport-level error, the system MUST treat that failure as recoverable transport state, rebuild the shared outbound HTTP client, and retry the failed model-refresh operation at most once for the current failover cycle. HTTP status failures, invalid upstream payloads, and permanent authentication failures MUST NOT trigger shared-client rotation.

#### Scenario: model fetch transport failure rotates the shared client once

- **WHEN** a model refresh attempts to fetch upstream models for an active account
- **AND** the fetch fails with a timeout, `aiohttp.ClientError`, or OS-level transport error before an upstream HTTP response is received
- **THEN** the system rotates the shared outbound HTTP client
- **AND** retries the model fetch once with the replacement client
- **AND** does not perform additional client rotations for later transport errors in the same failover cycle

#### Scenario: token refresh transport failure also rotates the shared client once

- **WHEN** model refresh needs to refresh an account token before fetching models
- **AND** the token refresh fails with a timeout, `aiohttp.ClientError`, or OS-level transport error before an upstream HTTP response is received
- **THEN** the system rotates the shared outbound HTTP client
- **AND** retries the token refresh once with the replacement client
- **AND** preserves existing permanent/non-permanent refresh error classification for non-transport failures

### Requirement: Shared outbound HTTP client rotation preserves in-flight users

Callers that use the default shared outbound HTTP session or retry client MUST lease the current shared client for the full duration of their upstream operation. Rotating the shared client MUST make new callers use the replacement client while deferring closure of the retired client until all active leases on that retired client have released. Process shutdown MAY force-close active and retired clients to keep shutdown bounded.

#### Scenario: in-flight request keeps using retired client until release

- **WHEN** an upstream operation acquires a lease on the current shared client
- **AND** model refresh rotates the shared client after a transport failure
- **THEN** new shared-client callers use the replacement client
- **AND** the retired client remains open until the in-flight operation releases its lease

#### Scenario: long-lived operations hold one lease across their whole upstream exchange

- **WHEN** a shared-client caller performs a streaming response, compact request, transcription request, usage fetch, token refresh, OAuth call, model fetch, or file create/finalize poll loop
- **THEN** the caller holds a shared-client lease until the operation has finished consuming the upstream response or poll loop
- **AND** a concurrent shared-client rotation does not close that operation's client mid-exchange

#### Scenario: shutdown force-closes active leases

- **WHEN** the application is shutting down
- **AND** active leases still exist on the current or retired shared client
- **THEN** global HTTP client close is allowed to force-close those clients instead of waiting indefinitely for long-lived streams
