## 1. Spec Delta

- [x] 1.1 Document retry-safe owner quota migration for direct Responses
  WebSocket follow-ups.
- [x] 1.2 Preserve fail-closed behavior for unsafe owner-bound continuations.

## 2. Implementation

- [x] 2.1 Add a strict helper for stripping `previous_response_id` only when a
  fresh full-resend request body is already marked retry-safe.
- [x] 2.2 Use the helper for owner quota failures during WebSocket connect and
  pre-created upstream error handling.

## 3. Verification

- [x] 3.1 Run focused WebSocket owner quota unit tests.
- [x] 3.2 Validate the OpenSpec change.
