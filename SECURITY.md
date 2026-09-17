# Security policy

## Supported versions

While the project is pre-1.0, only the latest released version receives security fixes.

| Version | Supported |
|---|---|
| latest | yes |
| older | no |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report privately through [GitHub Security Advisories](https://github.com/biniyam-mulugeta/Offsetscope/security/advisories/new), which lets us discuss and fix the issue before it becomes public.

Please include:

- What the issue is and roughly how serious you think it is
- Steps to reproduce, or a proof of concept
- The affected version and your deployment shape (auth mode, reverse proxy, broker type)
- Any suggested fix

You can expect an acknowledgement within a few days and an assessment shortly after. We will credit you in the advisory and the changelog unless you prefer otherwise.

## Scope

In scope:

- Authentication or authorisation bypass, including role escalation
- Escaping the read-only mode
- CSRF, XSS, or session handling flaws
- Leaking cluster credentials through the API, logs, or the UI
- Exposing message content that masking should have covered
- Container escape or privilege escalation in the shipped image

Out of scope:

- Running `AUTH_MODE=none` on a reachable interface. This is documented, requires an explicit acknowledgement flag, and shows a permanent warning banner.
- Anything requiring an attacker to already hold valid admin credentials.
- Vulnerabilities in a Kafka broker, Schema Registry, or Prometheus rather than in this console.
- Missing hardening on a deployment that ignores the checklist in [`docs/security.md`](docs/security.md).

## Design commitments

These are properties we intend to hold, and a break in any of them is a vulnerability:

- Kafka credentials never leave the backend — not in API responses, not in logs, not in the UI.
- Message payloads are never written to disk.
- Read-only mode is enforced at the service layer, not merely by hiding buttons in the UI.
- Every mutating action is recorded in the audit log.
- Revealing a masked value records **that** it happened, never the value itself.
- The console makes no outbound connections beyond the clusters, registries, and notification targets the operator configures.

## Supply chain

Every dependency is pinned exactly. No prebuilt image is published: you build the image yourself from this source with `docker compose up -d --build`, so what runs is exactly what you can read here.
