## MODIFIED Requirements

### Requirement: Accounts page

The Accounts page SHALL display a two-column layout: left panel with searchable account list, import button, and add account button; right panel with selected account details including usage, token info, and actions (pause/resume/delete/re-authenticate).

#### Scenario: Re-authenticate selected account
- **WHEN** a user clicks re-authenticate for a deactivated account
- **THEN** the app starts the OAuth flow with that selected account id as
  the re-authentication target
- **AND** a successful sign-in refreshes the selected account instead of
  creating a new account row
