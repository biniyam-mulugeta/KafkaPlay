# FAQ

### Do I need Prometheus?

No. The built-in sampler records consumer-group and log-end offsets into SQLite, so lag history, lag velocity, estimated time-to-catch-up, throughput, and the partition heatmap work against any broker with nothing else installed.

Prometheus is an optional add-on (`make dev PROFILE=metrics`) that unlocks broker-level and replication charts fed by JMX. Those specific charts show a "connect Prometheus to enable" state when it is absent; nothing else is affected.

### Will this add load to my brokers?

Very little, by design. Consumer lag is read through the AdminClient rather than by running a shadow consumer. Admin reads share a five-second TTL cache, so ten open browser tabs cost one broker call rather than ten. Every broker call has a timeout. Message scans only run when a user starts one, and they respect a scan budget you can cancel.

The sampler's cost scales with partition count; above `SAMPLER_MAX_PARTITIONS` it lengthens its own interval automatically.

### Does it work with Redpanda / MSK / Confluent Cloud / Event Hubs?

Yes, with the caveat that managed platforms implement different subsets of the Kafka admin API. The console probes capabilities when it connects and greys out unsupported features with an explanation, rather than showing a button that fails. See [`connections.md`](connections.md).

### Does it work with ZooKeeper-mode clusters?

Kafka 2.8+ in ZooKeeper mode works for read-only features. KRaft-specific views, such as the controller quorum, are hidden. Kafka 3.x and 4.x on KRaft are the primary targets.

### Can I use it with more than one cluster?

Yes. List them all in `config/clusters.yaml` and switch from the header. There is no "default" cluster anywhere in the backend — every request names the cluster explicitly.

### Are message payloads stored anywhere?

No. They stream to your browser and are forgotten. The database holds users, dashboards, saved searches, alert rules, the audit log, and sampled offsets — never message content.

The one exception is opt-in: a dashboard panel can be marked persistable, which stores **masked aggregates** with a retention window. It is off by default.

### Why is my masked IP showing as `203.0.113.xxx`?

That is masking working. Turn it off per cluster with `masking_enabled: false`, tune the rules per topic, or use the role-gated reveal on an individual message. A reveal is recorded in the audit log — the fact of it, not the value.

### I set `AUTH_MODE=none` and the container will not start

Deliberate. Inside Docker the app binds `0.0.0.0`, which is reachable from outside the container, so it refuses to run without authentication unless you also set `ALLOW_INSECURE_NO_AUTH=true`. Do that only on a machine where nothing else can reach the port.

### I lost the admin password

Stop the console, delete the user row, and restart — the bootstrap admin is recreated from `ADMIN_USERNAME` / `ADMIN_PASSWORD`:

```bash
docker compose exec console python -c \
  "import sqlite3; sqlite3.connect('/data/kafkaplay.db').execute('DELETE FROM users').connection.commit()"
docker compose restart console
```

### The cluster list is empty

Either `config/clusters.yaml` is not mounted, or it parsed to nothing. Check the startup log for `clusters=0` and confirm the `volumes:` entry. An empty list is a valid first-run state, not an error.

### Startup fails complaining about environment variables

Your `clusters.yaml` references `${VAR}` values that are not set. The error names every missing variable at once. Add them to `.env`, or give them defaults with `${VAR:-default}`.

### Can I rebrand it?

Yes. `APP_NAME` renames the product, and `THEME` selects a directory under `/app/themes` holding colours, fonts, a logo, and a favicon. Mount your own to rebrand with no rebuild. The name "KafkaPlay" appears only in the repository and image name.

### Is there telemetry?

None. The only outbound connections are the ones you configure.

### What is the licence?

Apache-2.0. All dependencies are permissively licensed — no copyleft obligations.
