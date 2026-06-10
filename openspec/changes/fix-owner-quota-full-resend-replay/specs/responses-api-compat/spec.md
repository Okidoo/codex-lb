## ADDED Requirements

### Requirement: Retry-safe owner quota failures may replay as fresh WebSocket requests

The proxy SHALL replay a Codex-native direct Responses WebSocket request pinned by `previous_response_id` to an owner account on another eligible account only when the owner returns a retryable account-recovery quota failure before any upstream response is created or visible output is emitted and the proxy already has a retry-safe fresh full-resend request body for the same client turn. The replay MUST remove `previous_response_id`, clear the preferred owner account, suppress the failed upstream event from downstream, and mark the failed owner through the normal stream-error health path.

#### Scenario: safe full resend migrates from a quota-exhausted owner

- **GIVEN** a direct Responses WebSocket request includes `previous_response_id`
  for `account_a`
- **AND** the proxy has captured a retry-safe fresh full-resend body for the
  same turn
- **WHEN** `account_a` returns `usage_limit_reached` before `response.created`
  or any visible output
- **THEN** the proxy strips `previous_response_id` from the replay body
- **AND** it may reconnect and replay the fresh body on `account_b`
- **AND** it does not emit the owner quota failure downstream

#### Scenario: unsafe owner continuation still fails closed

- **GIVEN** a direct Responses WebSocket request includes `previous_response_id`
  for `account_a`
- **AND** the proxy does not have a retry-safe fresh full-resend body
- **WHEN** `account_a` returns `usage_limit_reached`
- **THEN** the proxy emits the stable previous-response owner unavailable
  failure
- **AND** it does not replay the anchor-only continuation on another account

#### Scenario: file-bearing full-resend owner quota failures do not migrate

- **GIVEN** a direct Responses WebSocket request includes `previous_response_id`
  for `account_a`
- **AND** the proxy has captured a retry-safe fresh full-resend body
- **AND** that fresh body contains an `input_file.file_id` reference
- **WHEN** that owner returns an account-recovery quota failure
- **THEN** the proxy preserves the file-owner routing contract
- **AND** it does not replay the request on another account
