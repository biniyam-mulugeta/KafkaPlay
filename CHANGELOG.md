# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

First feature-complete state. Everything below is implemented, tested, and
verified against a live Kafka 3.9.1 KRaft broker.

### Added

**Foundations**
- Twelve-factor configuration; `config/clusters.yaml` with `${VAR}`,
  `${VAR:-default}` and `$${escaped}` substitution. Unknown keys are rejected
  at startup so a typo surfaces immediately, and missing variables are
  reported all at once.
- Multi-cluster throughout: no "default" cluster exists anywhere in the
  backend. PLAINTEXT, SSL/mTLS, SASL PLAIN, SCRAM-256/512, OAUTHBEARER and
  AWS MSK IAM.
- Capability probing per cluster, so features a broker cannot perform are
  hidden rather than offered and failing.
- Single image, non-root, multi-arch, no apt packages, ~160 kB initial JS.

**Reading**
- Cluster overview, topics with per-partition detail and configs, consumer
  groups with lag, and a replication view with `min.insync.replicas` headroom
  and broker balance.
- Message browser with a JMESPath filter DSL, scan budgets that report which
  limit ended a scan, live tail over WebSocket, and JSON/Avro/text/hex
  decoding with Schema Registry framing detected first.

**Metrics without Prometheus**
- A built-in sampler records consumer-group and log-end offsets into SQLite,
  giving lag history, lag velocity, time-to-catch-up, throughput and the
  partition heatmap on any broker with nothing else installed. Prometheus and
  JMX are an optional add-on.

**Operating**
- Topic CRUD, incremental config changes, produce, replay, preferred-leader
  election, and consumer-group deletion. Every destructive action has a dry
  run and a typed confirmation.
- Offset reset shows exactly how many records would be skipped or replayed,
  and refuses outright while the group has live members.
- Append-only audit log with scrubbed before/after snapshots and CSV export.
- Local users and OIDC, three roles, CSRF, and a global read-only mode that
  overrides roles.

**Beyond parity**
- Custom dashboards (throughput, split-by, histogram with thresholds, top-N,
  single stat) with JSON export/import.
- Topic flow map that marks measured edges apart from declared ones.
- Topic-to-topic latency tracer reporting p50/p95/p99.
- Alert rules with debounce and cooldown, delivered by HMAC-signed webhook,
  Slack, Teams or SMTP.
- Command palette, light/dark themes, English and Hungarian.

### Fixed

Bugs found by testing rather than by review, each of which would have reached
a user:

- `app = create_app()` at import time made the module unimportable without a
  complete environment, breaking pytest, ruff and mypy at once.
- The SPA catch-all route was only constructed when a frontend bundle existed,
  so it crashed the container on startup while passing every local test.
- `resolve_cluster` took a parameter that did not match its path parameter, so
  every cluster-scoped endpoint returned HTTP 422.
- Alert firing records were detached from their session, so the notifier
  raised `DetachedInstanceError` on the first real alert, and delivery
  outcomes were written to detached objects and silently lost.
- SQLite returns naive datetimes, so alert debounce arithmetic raised
  `TypeError` the first time a rule spanned two evaluation passes.
- `incremental_alter_configs` needs an explicit `AlterConfigOpType`; without
  it the broker rejected every config change.
- Config sources rendered as the raw integer `5` instead of `DEFAULT_CONFIG`.
- `at_min_isr` flagged every partition on an RF=1 cluster, where ISR equal to
  `min.insync.replicas` is the designed steady state.
- Light-mode `warn` was 4.24:1 against the surface, below WCAG AA. Contrast is
  now enforced by tests across both themes.

### Security

- Authentication resolves before the cluster lookup. Previously an
  unauthenticated caller received 404 for an unknown cluster and 401 for a
  real one, allowing cluster-name enumeration without logging in.
- Kafka credentials never appear in API responses, and a test asserts it.
- Login failures return one message whether or not the account exists, and an
  unknown user still costs a bcrypt comparison so timing does not leak.
- Passwords beyond bcrypt's 72-byte limit are rejected rather than silently
  truncated.
- Message scans use manual partition assignment and never commit, so they
  create no consumer group -- asserted by an integration test.
- Path traversal in the static file handler is confined to the bundle.
- An admin cannot demote, deactivate or delete their own account, and the last
  active admin cannot be removed.

[Unreleased]: https://github.com/biniyam-mulugeta/KafkaPlay/compare/main...HEAD
