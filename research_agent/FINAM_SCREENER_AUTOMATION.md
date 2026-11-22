# Finam AI Screener scheduled automation — bootstrap gate

This change is deliberately isolated to the research repository. It does not
touch the production scanner, options scanner, Telegram delivery, Finam Trade
API, account endpoints, or order execution.

## What is prepared

The manually triggered workflow
`.github/workflows/finam-screener-oauth-bootstrap.yml` verifies:

1. the published Finam OAuth metadata advertises the refresh-token grant;
2. the supplied refresh token can obtain an access token;
3. the authenticated MCP endpoint completes `initialize` and `tools/list`;
4. the read-only `screen_securities` tool is available.

The workflow does not request any screener rows yet. That next stage must be
built against the actual authenticated `tools/list` schema and a successful
read-only test call, including the provider's real pagination contract. No
assumed argument names or page semantics are hard-coded.

## Required GitHub Actions secrets

Add these three repository secrets in
**Settings → Secrets and variables → Actions**:

- `FINAM_MCP_ID` — Finam AI Screener client ID.
- `FINAM_MCP_TOKEN` — Finam AI Screener client secret/token.
- `FINAM_MCP_REFRESH_TOKEN` — refresh token from a publisher-supported
  one-time authorization flow.

Never put any of these values in source code, commits, issues, PR comments,
workflow inputs, or chat. Do not reuse a Finam Trade API token.

## Important authorization limitation

Finam's AI Screener setup guide documents ID + token and an interactive
**Authenticate** step. OAuth metadata previously inspected for this project
advertised refresh-token/offline-access support, but did not advertise
`client_credentials` or device-code grants. A GitHub Actions refresh flow is
therefore not proven until a legitimate refresh token is obtained through
Finam's supported authorization flow and this bootstrap passes.

Do not copy tokens out of editor storage or bypass the provider's login flow.
If Finam does not expose a supported way to obtain a refresh token, unattended
GitHub Actions collection is not available through this auth path; keep the
interactive Codespaces export as the fallback.

## Activation sequence

1. Add the three secrets above.
2. Run **Actions → Finam Screener OAuth Bootstrap → Run workflow** once.
3. Confirm `RESULT=AUTHENTICATED_READONLY_MCP_READY`.
4. Only then implement and test the 44-symbol collector using the exact
   `screen_securities` input schema and pagination metadata returned by Finam.
5. Run a real 44-symbol snapshot and compare it with the existing normalizer.
6. Enable a weekday schedule only after a successful end-to-end snapshot and
   artifact check.

The eventual schedule should run once per weekday after the MOEX session opens.
Do not enable a cron schedule in this bootstrap-only stage.

## Safety and data interpretation

- Only `screen_securities` may be called by the eventual collector.
- No accounts, portfolios, orders, alerts, presets, or trading methods.
- Raw provider responses and normalized snapshots stay in the research export
  path and Actions artifacts; do not connect them to production signals.
- Quote freshness remains UNKNOWN unless Finam supplies a verifiable quote
  timestamp. Retrieval time is not quote time.
- Missing/null values are reported, never imputed.
- If a refresh token rotates, the bootstrap stops rather than silently losing
  the new token; update the GitHub secret through the supported secure path.
