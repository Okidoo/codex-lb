## Why

The dashboard re-authenticate action currently reuses the generic OAuth
add-account flow. When overwrite-on-import is disabled, that generic flow
creates a duplicate account row. The duplicate does not carry the
deactivated account's proxy settings, so re-authenticating a proxied
account can silently move it to direct egress.

## What Changes

- Thread the selected account id through the dashboard OAuth flow when
  re-authenticating a deactivated account.
- Persist successful re-authentication into that existing account row
  instead of running generic add-account upsert/copy behavior.
- Preserve the stored proxy configuration and use it for server-side OAuth
  calls during targeted re-authentication.
- Add regression coverage for import-without-overwrite mode.

## Impact

- Re-authentication no longer creates proxy-less duplicate accounts.
- Generic add-account OAuth behavior is unchanged.
- If a targeted re-authentication returns credentials for a different
  upstream account/email, the existing row is not overwritten.
