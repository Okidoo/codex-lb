# Fix owner quota full-resend replay

## Why

Codex-native Responses WebSocket follow-ups can include both a
`previous_response_id` anchor and a retry-safe full resend body. When the owner
account for that anchor hits `usage_limit_reached`, codex-lb currently rewrites
the failure into `previous_response_owner_unavailable` and stops. That preserves
account ownership, but it also blocks a safe migration path that does not depend
on the exhausted owner's anchor.

## What Changes

- Allow owner-pinned WebSocket quota failures to replay on another account only
  when the proxy has a retry-safe fresh request body.
- Strip `previous_response_id` and clear the preferred account before replaying
  that safe full resend.
- Keep the existing fail-closed behavior for anchor-only continuations, file-id
  pinned requests, and requests that already emitted visible upstream output.

## Impact

- **Spec**: `responses-api-compat`
- **Behavior**: Codex-native full-resend follow-ups can migrate away from a
  spend-capped owner account without leaking the raw quota event downstream.
