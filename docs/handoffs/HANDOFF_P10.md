# P10 handoff: workflow and plugin security

## Implemented

- Slack signature helper verifies raw body bytes with `v0=` HMAC-SHA256 and a strict 300-second timestamp window.
- Email approval view is read-only; confirmation helper requires authenticated explicit POST.
- MCP manifest hashes are pinned by tenant/server; drift and sensitive external execution fail closed. Destinations use the shared public URL/SSRF validation.
- Outbound webhooks are timestamp-signed with HMAC-SHA256, idempotency delivery IDs, ten-second HTTP timeout, public-target validation, redirects disabled, and bounded retries.
- Added forced RLS coverage for approval channel configs, MCP registrations, outbound webhook configs, and delivery history.

## Remaining P10 gates

- Channel helpers are not connected to Slack/Teams/email OAuth credentials or approval UI routes. Teams Bot Framework JWT validation and approver identity/role mapping are absent.
- Approval expiration/escalation is not a durable scheduled worker, and `ISSUED` Gatekeeper state does not yet implement the full immutable PENDING/APPROVED/REJECTED/EXPIRED lifecycle.
- Outbound delivery is a callable async adapter, not an ARQ queue with tenant subscription management, durable retry cursor, DLQ, or admin history API.
- Remote MCP OAuth 2.1/PKCE, RFC 8707/9728/9207 discovery, strict Host/Origin transport, persistent pin approval workflow, and container sandbox are not implemented. No third-party plugin is executed.
- Webhook and Slack helpers were tested locally with synthetic signatures only; no live provider endpoints or credentials were used.
