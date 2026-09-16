# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Project skeleton** — FastAPI backend, React 19 + TypeScript frontend, single-image packaging, Apache-2.0 licence.
- **Configuration** — twelve-factor settings, plus `config/clusters.yaml` with `${VAR}`, `${VAR:-default}` and `$${escaped}` substitution. Unknown keys are rejected at startup so typos surface immediately, and missing variables are reported all at once.
- **Multi-cluster from the start** — a thread-safe registry with no "default" cluster anywhere in the backend. Cluster models cover PLAINTEXT, SSL/mTLS, SASL PLAIN, SCRAM-SHA-256/512, OAUTHBEARER, and AWS MSK IAM.
- **Authentication** — local accounts with bcrypt, signed-cookie sessions, double-submit CSRF, and `viewer` / `operator` / `admin` roles with optional per-cluster scoping.
- **Read-only mode** — global `READ_ONLY` and per-cluster `read_only`, enforced ahead of the role check so an admin cannot write while it is on.
- **`AUTH_MODE=none` guard** — refused on a non-loopback bind unless explicitly acknowledged, with a permanent UI banner.
- **Health endpoints** — `/healthz` for liveness and `/readyz` for readiness. Neither contacts a broker, because restarting the console cannot fix someone else's cluster.
- **Theme system** — `themes/<name>/theme.json` applied at runtime, so the image is white-labelable without a rebuild. Ships `kafkaplay` and `neutral`, both with light and dark palettes derived from one token set. A broken theme falls back rather than failing.
- **Internationalisation** — English and Hungarian, with all strings in locale files.
- **App shell** — collapsible sidebar, header with theme and language switches, skip link, visible focus rings, and status colours that never rely on hue alone.
- **Structured logging** — JSON to stdout with credential redaction applied by a processor rather than by convention.
- **Development stack** — single-node KRaft broker by default, with `cluster` (3 brokers, racks) and `metrics` (Prometheus, kafka-exporter) profiles. A generic seeder produces `orders`, `clickstream`, `app-logs`, `payments` (Avro), and `audit-trail`, and runs a consumer group that lags on purpose.
- **CI** — lint, type-check, unit tests, an integration matrix across Kafka 3.9, Kafka 4.x and Redpanda, a Playwright smoke test, image build with Trivy scanning, and a multi-arch release workflow publishing to GHCR with provenance and an SBOM.
- **Documentation** — README, configuration reference, connection cookbook, security guide, and FAQ.

### Security

- Cluster credentials are never returned by the API, and the cluster listing is covered by a test asserting that.
- Login failures return one message whether or not the account exists, and an unknown user still costs a bcrypt comparison so timing does not leak.
- Passwords over bcrypt's 72-byte limit are rejected rather than silently truncated.
- The image runs as a non-root user; the production compose file adds `read_only`, `no-new-privileges`, and a tmpfs for `/tmp`.

[Unreleased]: https://github.com/<owner>/kafkaplay/compare/main...HEAD
