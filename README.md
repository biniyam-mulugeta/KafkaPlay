# KafkaPlay

A self-hosted web console for operating **any** Apache Kafka cluster — self-managed, Confluent Cloud, Aiven, AWS MSK, Redpanda, or Azure Event Hubs.

Browse topics and messages, watch consumer lag over time, reset offsets safely, and build your own dashboards. Apache-2.0 licensed, no telemetry, no external calls.

> **Status: in development.** Milestone 1 (skeleton, theming, auth) is complete. Topics, messages, and metrics land in milestones 2–4. See [Roadmap](#roadmap).

---

## Why another Kafka console?

Most Kafka UIs need Prometheus and a JMX exporter before they can draw a lag chart. Managed clusters rarely expose JMX at all, so those charts stay empty where you need them most.

KafkaPlay ships a **built-in sampler**: it records consumer-group and log-end offsets into SQLite on a schedule. Lag history, lag velocity, estimated time-to-catch-up, throughput, and the partition heatmap all work out of the box, against any broker, with nothing else installed. Prometheus and JMX remain supported as an **optional** add-on for broker-level and replication metrics.

It is also careful with your brokers: lag comes from the AdminClient rather than a shadow consumer, admin reads share a short TTL cache so ten open tabs cost one broker call, and message scans only run when you start one.

---

## 60-second quick start

```bash
git clone https://github.com/<your-account>/kafkaplay.git
cd kafkaplay
cp .env.example .env

# SESSION_SECRET is the only required setting.
python3 -c 'import secrets; print("SESSION_SECRET=" + secrets.token_urlsafe(32))' >> .env

cp config/clusters.example.yaml config/clusters.yaml
# ...point bootstrap_servers at your broker...

docker compose up -d
```

Open <http://127.0.0.1:8080>. The first admin password is printed once in the logs unless you set `ADMIN_PASSWORD`:

```bash
docker compose logs console | grep generated_admin_password
```

### Try it with no cluster of your own

```bash
make dev
```

This starts a single-node KRaft broker, Schema Registry, and a seeder that produces to `orders`, `clickstream`, `app-logs`, `payments` (Avro), and `audit-trail` — including a consumer group that lags on purpose so the lag features have something to show. Log in as `admin` / `kafkaplay-dev-password`.

```bash
make dev PROFILE=cluster   # 3 brokers with racks, for replication work
make dev PROFILE=metrics   # adds Prometheus + kafka-exporter
make dev-down              # stop and delete volumes
```

---

## Connecting to your cluster

Clusters are defined in `config/clusters.yaml`, with `${VAR}` substitution so secrets stay in `.env`:

```yaml
clusters:
  - name: production
    label: Production
    bootstrap_servers: broker-1:9093,broker-2:9093
    security_protocol: SASL_SSL
    read_only: true              # even admins cannot write to this one
    sasl:
      mechanism: SCRAM-SHA-512
      username: ${KAFKA_USERNAME}
      password: ${KAFKA_PASSWORD}
    tls:
      ca_location: /config/certs/ca.pem
```

Supported: PLAINTEXT, SSL/mTLS, SASL PLAIN, SCRAM-SHA-256/512, OAUTHBEARER (OIDC), and AWS MSK IAM. Several clusters can be listed and switched from the header.

**Networking.** `docker-compose.yml` deliberately assumes nothing about your Docker network. Three setups are documented in [`docs/connections.md`](docs/connections.md): brokers in the same compose project, brokers on an existing external network, and brokers on the host or a remote host (including the `advertised.listeners` pitfalls that catch everyone).

When a broker does not support an admin API — Redpanda and older ZooKeeper-mode clusters differ here — the console greys out that feature with an explanation instead of failing.

---

## Safety

This is built on the assumption that you will point it at production.

- **`READ_ONLY=true`** disables every write globally, overriding user roles. A per-cluster `read_only: true` does the same for one cluster.
- **Roles**: `viewer` (read-only), `operator` (produce, reset offsets), `admin` (topics, ACLs, users). Optionally scoped per cluster.
- **Destructive actions require a dry run first**, showing exactly what would change, plus typed confirmation.
- **Every write is audited**: who, what, when, before/after, and the result.
- **Masking is on by default** — IPv4/IPv6, email, card-like numbers, and JWTs are masked in every message view, with per-cluster and per-topic rules. **Message payloads are never written to disk.**
- **No telemetry.** The only outbound connections are to your clusters, your Schema Registry, your Prometheus, and notification targets you configure.

### A note on `AUTH_MODE=none`

There is a no-authentication mode for local development. Every visitor is an administrator. It is refused on a non-loopback bind unless you set `ALLOW_INSECURE_NO_AUTH=true`, and the UI shows a permanent banner. Inside Docker the app always binds `0.0.0.0`, so containers must set that flag explicitly — deliberate friction, not a bug.

---

## Remote access

Nothing is exposed publicly by default; the container binds to `127.0.0.1`. To reach a server instance:

```bash
ssh -L 8080:localhost:8080 user@server
```

For a permanent deployment, put a reverse proxy with TLS in front and set `SECURE_COOKIES=true`. See [`docs/security.md`](docs/security.md).

---

## Theming

The UI ships with two themes and is white-labelable without rebuilding the image. A theme is a directory:

```
themes/<name>/
  theme.json     colours (light + dark), fonts, product name, favicon
  logo.svg       optional; falls back to a text wordmark when absent
```

Select with `THEME=<name>`, rename the product with `APP_NAME`, and mount your own directory over `/app/themes`. Both light and dark palettes derive from the same tokens. Status colours are kept distinct from brand colours and are always paired with an icon or shape, never colour alone.

Interface languages: English and Hungarian (`DEFAULT_LOCALE`).

---

## Roadmap

| Milestone | Contents | Status |
|---|---|---|
| 1 | Skeleton, theming, i18n, auth, CI | ✅ done |
| 2 | Cluster overview, topics, consumer groups + lag, replication | next |
| 3 | Message browser, JMESPath search, live tail, masking | |
| 4 | Built-in sampler, lag history, heatmap, optional Prometheus | |
| 5 | Admin actions with dry-run, config drift, audit log, roles | |
| 6 | Alert rules, notification centre, webhook/Slack/Teams/SMTP | |
| 7 | Custom dashboards, topic flow map, latency tracer | |
| 8 | OIDC, Schema Registry browser, ACLs, command palette | |
| 9 | Accessibility, docs, screenshots, release | |

---

## Development

```bash
make install    # venv + npm install
make backend    # API on :8080 with reload
make frontend   # Vite dev server on :5173, proxied to the backend
make test       # backend + frontend unit tests
make lint       # ruff, mypy, eslint, tsc
```

Integration tests need a broker and skip without one:

```bash
KAFKAPLAY_TEST_BOOTSTRAP=localhost:9092 make test-integration
```

CI runs the integration suite against Kafka 3.9, Kafka 4.x, and Redpanda.

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Documentation

- [`docs/configuration.md`](docs/configuration.md) — every setting
- [`docs/connections.md`](docs/connections.md) — MSK, Confluent Cloud, Aiven, Redpanda, Event Hubs, networking
- [`docs/security.md`](docs/security.md) — reverse proxy, TLS, OIDC, hardening
- [`docs/faq.md`](docs/faq.md)

## License

[Apache-2.0](LICENSE).
