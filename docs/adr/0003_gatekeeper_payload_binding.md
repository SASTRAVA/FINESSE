# ADR 0003: Bind approval to the exact action payload

- **Status:** Accepted for the existing Gatekeeper token/record flow; canonicalization interoperability remains limited.
- **Decision:** Include tenant, actor, tool, arguments, nonce, purpose, and expiry in the signed approval claims and compare the approved action to the submitted arguments before one-time consumption.
- **Reason:** An agent must not alter recipients, URLs, or side-effect arguments after a person approves an action.
- **Consequences:** Any payload mutation requires a new approval. Approval views should show the exact execution target and body. Cross-language consumers must use the same canonicalization rules; RFC 8785 interoperability is not claimed.
- **Evidence:** `engine/auth/security.py` and Gatekeeper contract tests.
