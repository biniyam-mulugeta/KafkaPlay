# Connection cookbook

How to reach your brokers from the console container, and the provider-specific settings that work.

---

## Part 1: networking

The single most common failure is not authentication — it is `advertised.listeners`. A client connects to `bootstrap_servers`, receives the broker's *advertised* addresses in the metadata response, and then connects to **those**. If the advertised address is not resolvable from inside the console container, the connection appears to succeed and then times out.

Check what your brokers actually advertise before debugging anything else:

```bash
docker exec <broker> /opt/kafka/bin/kafka-broker-api-versions.sh \
  --bootstrap-server localhost:9092 | head -3
```

### (a) Brokers in the same compose project

Simplest case. Add the console to your existing `docker-compose.yml` and reference brokers by service name.

```yaml
services:
  console:
    image: ghcr.io/<owner>/kafkaplay:latest
    ports: ["127.0.0.1:8080:8080"]
    environment:
      SESSION_SECRET: ${SESSION_SECRET}
    volumes:
      - ./config:/config:ro
      - kafkaplay_data:/data
```

```yaml
# config/clusters.yaml
clusters:
  - name: local
    bootstrap_servers: kafka:9092
```

Brokers must advertise `kafka:9092`, not `localhost:9092`.

### (b) Brokers on another compose project's network

Find the real network name — do not guess it:

```bash
docker network ls
docker inspect <broker-container> -f '{{json .NetworkSettings.Networks}}' | python3 -m json.tool
```

Set it in `.env` and uncomment the two `networks:` blocks in `docker-compose.yml`:

```bash
KAFKA_NETWORK=myproject_default
```

The console joins that network as an external network and reaches brokers by their service name. This is the right choice when the broker publishes no host port — and it keeps working if that port mapping is removed later.

### (c) Broker on the host, or remote

A remote broker needs nothing special: put its address in `bootstrap_servers`.

A broker on the **same host as Docker** is the awkward case, because `localhost` inside a container is the container.

| Host OS | Use |
|---|---|
| Linux | `extra_hosts: ["host.docker.internal:host-gateway"]`, then `host.docker.internal:9092` |
| macOS / Windows | `host.docker.internal:9092` works already |
| Any | `network_mode: host` (Linux only), then `localhost:9092` |

The broker must advertise an address the container can resolve. If it advertises `localhost:9092`, the container will try to connect to itself and fail.

---

## Part 2: providers

### Self-managed, SASL/SCRAM over TLS

```yaml
clusters:
  - name: production
    bootstrap_servers: broker-1:9093,broker-2:9093,broker-3:9093
    security_protocol: SASL_SSL
    read_only: true
    sasl:
      mechanism: SCRAM-SHA-512
      username: ${KAFKA_USERNAME}
      password: ${KAFKA_PASSWORD}
    tls:
      ca_location: /config/certs/ca.pem
```

Mount certificates read-only at `/config/certs` and reference them by container path.

### Mutual TLS

```yaml
    security_protocol: SSL
    tls:
      ca_location: /config/certs/ca.pem
      certificate_location: /config/certs/client.pem
      key_location: /config/certs/client.key
      key_password: ${CLIENT_KEY_PASSWORD}
```

### Confluent Cloud

API key and secret go over SASL `PLAIN` — which is safe here because the transport is TLS.

```yaml
    bootstrap_servers: pkc-xxxxx.eu-central-1.aws.confluent.cloud:9092
    security_protocol: SASL_SSL
    sasl:
      mechanism: PLAIN
      username: ${CONFLUENT_API_KEY}
      password: ${CONFLUENT_API_SECRET}
    schema_registry:
      url: https://psrc-xxxxx.eu-central-1.aws.confluent.cloud
      username: ${SCHEMA_REGISTRY_USERNAME}
      password: ${SCHEMA_REGISTRY_PASSWORD}
```

Schema Registry uses a **separate** API key from the cluster.

### Aiven

Aiven issues a CA certificate per project. Either SASL/SCRAM or mTLS:

```yaml
    bootstrap_servers: kafka-xxxxx.aivencloud.com:12345
    security_protocol: SASL_SSL
    sasl:
      mechanism: SCRAM-SHA-512
      username: ${AIVEN_USERNAME}
      password: ${AIVEN_PASSWORD}
    tls:
      ca_location: /config/certs/aiven-ca.pem
```

### AWS MSK with IAM

Requires the `msk` extra, which pulls in boto3. Standard AWS credential resolution applies (instance role, environment, or profile).

```yaml
    bootstrap_servers: b-1.example.kafka.eu-central-1.amazonaws.com:9098
    security_protocol: SASL_SSL
    sasl:
      mechanism: AWS_MSK_IAM
      aws_region: eu-central-1
      # aws_profile: my-profile
```

Port `9098` is IAM. `9094` is TLS, `9096` is SCRAM — use the matching mechanism.

### Redpanda

Behaves as a Kafka cluster; `PLAINTEXT` or `SASL_SSL` both work. Redpanda exposes no JMX, so JMX-only charts stay unavailable — the built-in sampler covers lag and throughput regardless. A few admin APIs differ; the console detects this at connect time and greys them out.

### Azure Event Hubs (Kafka endpoint)

```yaml
    bootstrap_servers: <namespace>.servicebus.windows.net:9093
    security_protocol: SASL_SSL
    sasl:
      mechanism: PLAIN
      username: $$ConnectionString
      password: ${EVENTHUBS_CONNECTION_STRING}
```

The username is the literal string `$ConnectionString`. It is written `$$ConnectionString` above because `${...}` is substitution syntax and `$$` escapes it.

Event Hubs implements a subset of the Kafka admin API: consumer groups must be pre-created in Azure, and topic creation and ACL management are unavailable. Those features grey out automatically.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Connects, then times out listing topics | `advertised.listeners` is not resolvable from the container |
| `SASL authentication failed` | Wrong mechanism — SCRAM-SHA-512 vs SCRAM-SHA-256 vs PLAIN |
| `SSL handshake failed` | Missing or wrong `ca_location`; self-signed chain |
| `Broker transport failure` immediately | Wrong port, or `security_protocol` does not match the listener |
| Console starts but the cluster list is empty | `config/clusters.yaml` not mounted; check the `volumes:` entry |
| Startup fails naming environment variables | A `${VAR}` in `clusters.yaml` is unset; add it to `.env` |
| Some buttons are greyed out | The broker does not support that admin API — hover for the reason |
