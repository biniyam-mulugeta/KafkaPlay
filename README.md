# KafkaPlay

A self-hosted web console for operating **any** Apache Kafka cluster — self-managed, Confluent Cloud, Aiven, AWS MSK, Redpanda, or Azure Event Hubs.

Browse topics and messages, watch consumer lag over time, reset offsets safely, and build your own dashboards. Apache-2.0 licensed, no telemetry, no external calls.

> **Status: feature-complete, pre-1.0.** All nine milestones are implemented and tested against live Kafka 3.9 in CI, alongside Kafka 4.x and Redpanda. Expect rough edges before 1.0; please report them.

---

## Why another Kafka console?

Most Kafka UIs need Prometheus and a JMX exporter before they can draw a lag chart. Managed clusters rarely expose JMX at all, so those charts stay empty where you need them most.

KafkaPlay ships a **built-in sampler**: it records consumer-group and log-end offsets into SQLite on a schedule. Lag history, lag velocity, estimated time-to-catch-up, throughput, and the partition heatmap all work out of the box, against any broker, with nothing else installed. Prometheus and JMX remain supported as an **optional** add-on for broker-level and replication metrics.

It is also careful with your brokers: lag comes from the AdminClient rather than a shadow consumer, admin reads share a short TTL cache so ten open tabs cost one broker call, and message scans only run when you start one.

---

## Quick start

```bash
git clone https://github.com/biniyam-mulugeta/kafkaplay.git
cd kafkaplay
docker compose up -d --build
```

That is the whole setup. No `.env`, no config file, no secrets to generate.

Open <http://127.0.0.1:8080>, register the first account — **it becomes the
administrator** — and add your cluster from the UI. The connection is tested
before it is saved, so a wrong broker address or SASL mechanism is caught
immediately rather than showing up as an empty topic list later.

Registration then closes automatically. Add colleagues from Settings, or set
`ALLOW_SIGNUP=true` to let them register themselves as viewers.

### Prefer to configure it up front?

Everything is optional, in `.env` beside the compose file:

```bash
KAFKA_BOOTSTRAP_SERVERS=broker:9092   # skip the "add a cluster" step
ADMIN_USERNAME=admin                  # pre-create an admin instead of
ADMIN_PASSWORD=at-least-12-chars      #   registering the first account
READ_ONLY=true                        # block every write, even for admins
CONSOLE_PORT=8090                     # if 8080 is taken
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

There are three ways to tell the console about a cluster. Pick one.

| Method | Best for | How |
|---|---|---|
| **The UI** | Most people | **Settings → Add a cluster** (or the prompt shown when no cluster exists). Admins only. |
| **One environment variable** | A single PLAINTEXT cluster | `KAFKA_BOOTSTRAP_SERVERS=...` in `.env` |
| **`config/clusters.yaml`** | TLS/SASL, several clusters, config kept in git | See [below](#clustersyaml) |

If the same name is defined twice, `clusters.yaml` wins over the UI, and the UI wins over the environment variable.

### Step 1: Work out where your broker is

The console runs **inside a container**. Inside a container, `localhost` means the container itself, not your machine, so `localhost:9092` never works. Which address to use depends on where Kafka runs:

| Where Kafka runs | Bootstrap servers to use | Extra setup |
|---|---|---|
| On another server or a managed service | Its normal address, e.g. `broker.example.com:9092` | None |
| Directly on the same machine (not in Docker) | `host.docker.internal:<port>` | A Docker listener on the broker, see [below](#kafka-installed-directly-on-this-machine) |
| In a Docker container | `<container-name>:9092` | Put the console on the broker's network, see [below](#kafka-running-in-docker) |

Not sure which case you're in? Run:

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}\t{{.Networks}}'
```

If no Kafka container is listed, Kafka is either installed directly on your machine or remote. To check whether it's on this machine:

```bash
ss -ltnp | grep -E ':(9092|9093|9094)\b'
```

### Step 2: Add the cluster

**In the UI:** open **Settings → Add a cluster** and fill in:

- **Name:** any short identifier you like, e.g. `local` or `production`. It can use letters, digits, `.`, `_` and `-`. It only labels the cluster inside KafkaPlay and does not have to match anything in Kafka.
- **Bootstrap servers:** the address from Step 1, e.g. `host.docker.internal:9094`. Separate several brokers with commas.
- **Security:** `PLAINTEXT` for a local broker without authentication. Choose SASL/SSL and fill in the credentials for a secured cluster.
- **Schema Registry URL** and **Read-only** are optional.

Click **Test connection**. It must report your brokers and topics before **Add cluster** is enabled, so a wrong address is caught here and not later as an empty topic list.

**Or, without the UI,** add this to `.env` beside `docker-compose.yml` and restart:

```bash
KAFKA_BOOTSTRAP_SERVERS=host.docker.internal:9094
KAFKA_CLUSTER_NAME=local      # optional, defaults to "kafka"
```

```bash
docker compose up -d
```

### Kafka installed directly on this machine

This is the case that trips most people up, and it's usually not the address you typed but the one Kafka sends back.

A client connects to the bootstrap address, and Kafka replies with the address it wants the client to use from then on, called its **advertised listener**. A downloaded Kafka advertises `localhost:9092`. The console reaches your broker, is told to use `localhost:9092`, connects to itself, and fails.

The fix is a second listener just for Docker. Clients on your machine keep using `localhost:9092` as before.

1. See your current settings (adjust the path to your Kafka directory):

   ```bash
   cd ~/kafka_2.13-4.3.1
   grep -nE '^(listeners|advertised.listeners|listener.security.protocol.map|controller.listener.names)=' config/server.properties
   ```

2. Edit those lines in `config/server.properties` so they include a `DOCKER` listener. Keep the `CONTROLLER` entries your file already has:

   ```properties
   listeners=PLAINTEXT://:9092,DOCKER://:9094,CONTROLLER://:9093
   advertised.listeners=PLAINTEXT://localhost:9092,DOCKER://host.docker.internal:9094
   listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,DOCKER:PLAINTEXT
   ```

3. Restart Kafka:

   ```bash
   bin/kafka-server-stop.sh
   bin/kafka-server-start.sh -daemon config/server.properties
   ```

4. Add the cluster with bootstrap servers **`host.docker.internal:9094`**.

`docker-compose.yml` already maps `host.docker.internal` to your machine, so this works on plain Linux Docker as well as Docker Desktop.

> **Docker Desktop on Windows with Kafka inside WSL:** here `host.docker.internal` points to Windows, not to WSL. Use your WSL IP address instead, in both `advertised.listeners` and the UI. Find it with `hostname -I | awk '{print $1}'`. It can change when WSL restarts. To check which Docker you have, run `docker info --format '{{.OperatingSystem}}'`: it prints `Docker Desktop` for Docker Desktop.

### Kafka running in Docker

A broker in a container is reachable by its container name, but only from containers on the same Docker network.

1. Find the broker's network name:

   ```bash
   docker inspect <broker-container> -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}'
   ```

2. Put it in `.env`:

   ```bash
   KAFKA_NETWORK=myproject_default
   ```

3. In `docker-compose.yml`, uncomment the `networks:` block under the service and the `networks:` block at the bottom, then run `docker compose up -d`.

4. Add the cluster with bootstrap servers `<broker-container>:9092`.

The broker must advertise its container name (e.g. `PLAINTEXT://kafka:9092`), not `localhost`. Check what it advertises with:

```bash
docker exec <broker-container> /opt/kafka/bin/kafka-broker-api-versions.sh \
  --bootstrap-server localhost:9092 | head -3
```

### Troubleshooting a connection

If **Test connection** fails or topics don't show up, run these checks from your machine. Replace `host.docker.internal:9094` with your own address.

```bash
# 1. Is Kafka listening? It should show 0.0.0.0 or *, not only 127.0.0.1.
ss -ltnp | grep -E ':(9092|9093|9094)\b'

# 2. Can the console container open a TCP connection to the broker?
docker exec kafkaplay python -c "import socket; socket.create_connection(('host.docker.internal', 9094), 5); print('TCP OK')"

# 3. The same request the UI makes: which brokers and topics does Kafka return?
docker exec kafkaplay python -c "
from confluent_kafka.admin import AdminClient
md = AdminClient({'bootstrap.servers': 'host.docker.internal:9094'}).list_topics(timeout=10)
print('brokers:', [(b.host, b.port) for b in md.brokers.values()])
print('topics:', [t for t in md.topics if not t.startswith('__')])"

# 4. Which clusters has the console saved from the UI?
docker exec kafkaplay python -c "
import sqlite3
rows = sqlite3.connect('/data/kafkaplay.db').execute('select name, bootstrap_servers from stored_clusters').fetchall()
print(rows or 'no clusters saved')"
```

| What you see | Meaning | Fix |
|---|---|---|
| #1 shows nothing on your port | Kafka isn't running, or didn't pick up the new config | Check `server.properties` and restart Kafka |
| #1 shows only `127.0.0.1:<port>` | Kafka accepts connections from this machine only | Use `DOCKER://:9094` in `listeners`, with no host before the port |
| #2 fails | The container can't reach the broker at all | Wrong address or port, a firewall, or the wrong Docker network |
| #3 lists `localhost` as a broker | Kafka is advertising an address the container can't use | Fix `advertised.listeners`, see above |
| #3 prints your topics, but the UI shows none | The connection is fine, the cluster just isn't registered | Add it in the UI with exactly the address used in #3 |
| #4 shows an old address such as `localhost:9092` | A cluster was saved before Kafka was fixed | Remove it in **Settings** and add it again |

After adding a cluster, reload the page. If you have several, pick the right one in the header's cluster switcher.

### clusters.yaml

For secured clusters or several at once, declare them in `config/clusters.yaml` (mounted read-only into the container). `${VAR}` references are filled from the container's environment, so secrets stay out of the file:

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

Put the values in `.env`, and pass each one through in `docker-compose.yml` under `environment:` (e.g. `KAFKA_PASSWORD: ${KAFKA_PASSWORD}`). Compose does not hand every `.env` variable to the container on its own. The console refuses to start if a referenced variable is missing, and names it.

Supported: PLAINTEXT, SSL/mTLS, SASL PLAIN, SCRAM-SHA-256/512, OAUTHBEARER (OIDC), and AWS MSK IAM. Clusters defined here can't be removed from the UI.

Settings for Confluent Cloud, Aiven, AWS MSK, Redpanda and Azure Event Hubs are in [`docs/connections.md`](docs/connections.md).

When a broker doesn't support an admin API (Redpanda and older ZooKeeper-mode clusters differ here), the console greys out that feature with an explanation instead of failing.

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

## What's in it

| Area | Features |
|---|---|
| **Cluster** | Brokers, KRaft controller, capability detection, partition health, read-only mode |
| **Topics** | Searchable list, per-partition leader/replicas/ISR/watermarks, configs with non-defaults highlighted, consumer groups per topic |
| **Consumer groups** | State, members, assignments, lag per partition and total — all from the AdminClient, never a shadow consumer |
| **Messages** | Browse from newest/oldest/offset/timestamp, JMESPath filter DSL, scan budgets, live tail over WebSocket, JSON/Avro/text/hex decoding |
| **Metrics** | Lag history, lag velocity and time-to-catch-up, throughput, partition heatmap — from the built-in sampler, no Prometheus needed |
| **Replication** | Replica matrix, RF vs `min.insync.replicas` headroom, broker balance, preferred-leader election |
| **Admin** | Topic CRUD, incremental config changes with diff, offset reset with dry-run and typed confirmation, produce, replay |
| **Alerts** | Six rule kinds with debounce and cooldown, notification centre, webhook (HMAC-signed), Slack, Teams, SMTP |
| **Dashboards** | Build your own panels: throughput, split-by, histogram with thresholds, top-N, single stat. Export/import as JSON |
| **Flow map** | Topics → consumer groups → topics, with measured edges marked apart from declared ones |
| **Latency tracer** | Correlate two topics by key and report p50/p95/p99 |
| **Schemas** | Subjects, versions, diffs, compatibility checks |
| **ACLs** | List, filter, create, delete — with an honest message when no authorizer exists |
| **Security** | Local + OIDC auth, three roles, CSRF, full audit log, masking on by default |
| **UX** | Command palette (⌘K), light/dark themes, English + Hungarian, WCAG AA contrast enforced by tests |

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
