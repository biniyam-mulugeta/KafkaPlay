# Configuration reference

Configuration comes from three places:

| Source | Holds | Reloaded |
|---|---|---|
| Environment / `.env` | deployment settings and secrets | on restart |
| `config/clusters.yaml` | cluster definitions | on restart |
| `themes/<name>/theme.json` | branding | on request |

Everything is twelve-factor, so the same image runs unchanged in Docker, Compose, or Kubernetes.

---

## Identity and appearance

| Variable | Default | Meaning |
|---|---|---|
| `APP_NAME` | `Offsetscope` | Product name in the UI and tab title |
| `THEME` | `offsetscope` | Directory under `THEMES_DIR` to load |
| `THEMES_DIR` | `/app/themes` | Where themes live; mount your own over this |
| `DEFAULT_LOCALE` | `en` | `en` or `hu` |

A theme that fails to parse falls back to the built-in palette and `APP_NAME`, rather than taking the console down.

## Serving

| Variable | Default | Meaning |
|---|---|---|
| `CONSOLE_HOST` | `0.0.0.0` in image | Bind interface inside the container |
| `CONSOLE_PORT` | `8080` | Bind port |
| `CONSOLE_BIND` | `127.0.0.1` | Host interface the compose file publishes on |
| `ROOT_PATH` | empty | Set when served under a reverse-proxy subpath |

`CONSOLE_BIND` is what keeps the console private. Changing it to `0.0.0.0` publishes it to your network.

## Safety

| Variable | Default | Meaning |
|---|---|---|
| `READ_ONLY` | `false` | Disables every write, overriding all roles |

Read-only is checked before the role check, so an admin cannot write while it is on. A per-cluster `read_only: true` in `clusters.yaml` does the same for one cluster. Either being true is enough.

## Authentication

| Variable | Default | Meaning |
|---|---|---|
| `AUTH_MODE` | `local` | `local`, `oidc`, or `none` |
| `SESSION_SECRET` | — | **Required** unless `AUTH_MODE=none`; ≥32 characters |
| `ALLOW_INSECURE_NO_AUTH` | `false` | Permits `AUTH_MODE=none` on a non-loopback bind |
| `ADMIN_USERNAME` | `admin` | First admin, created on an empty database |
| `ADMIN_PASSWORD` | empty | Generated and logged once if left blank |
| `SESSION_MAX_AGE_SECONDS` | `43200` | Session lifetime (12 hours) |
| `SECURE_COOKIES` | `false` | Set `true` when serving over HTTPS |

Rotating `SESSION_SECRET` invalidates every active session immediately. That is the intended emergency lever.

Passwords are bcrypt-hashed (cost 12) and must be 12–72 bytes. Over-length passwords are rejected rather than silently truncated, because bcrypt ignores bytes past 72 and would make two different long passwords interchangeable.

### Roles

| Role | Can |
|---|---|
| `viewer` | Read topics, groups, configs, metrics |
| `operator` | The above, plus produce and reset offsets |
| `admin` | The above, plus topic/ACL/user management |

## Clusters

| Variable | Default | Meaning |
|---|---|---|
| `CLUSTERS_FILE` | `/config/clusters.yaml` | Cluster definitions |

Substitution syntax inside the YAML:

| Form | Behaviour |
|---|---|
| `${VAR}` | Required — a missing variable is a startup error naming every one that is missing |
| `${VAR:-default}` | Optional, with a fallback |
| `$${VAR}` | A literal `${VAR}` |

Unknown keys are rejected at startup, so a typo becomes an error rather than a setting that silently does nothing.

## Metrics

| Variable | Default | Meaning |
|---|---|---|
| `SAMPLER_ENABLED` | `true` | Built-in offset sampler |
| `SAMPLER_INTERVAL_SECONDS` | `30` | Sampling period |
| `SAMPLER_RETENTION_DAYS` | `7` | How long samples are kept |
| `SAMPLER_MAX_PARTITIONS` | `2000` | Above this, the interval lengthens automatically |
| `PROMETHEUS_URL` | unset | Optional; unlocks broker/replication JMX charts |

The sampler stores **offsets only** — never message content. Lag history, velocity, time-to-catch-up, throughput, and the heatmap all work without Prometheus.

## Privacy

| Variable | Default | Meaning |
|---|---|---|
| `MASKING_ENABLED` | `true` | Masks sensitive values in every message view |

Built-in presets: `ipv4`, `ipv6`, `email`, `credit_card`, `jwt`. Per-cluster and per-topic rules go in `clusters.yaml` and may target JMESPath paths or use custom regex.

Message payloads are never persisted, regardless of this setting. Revealing a masked value is a role-gated action, and the audit log records **that** a reveal happened without storing the revealed value.

## Broker call budget

| Variable | Default | Meaning |
|---|---|---|
| `ADMIN_TIMEOUT_SECONDS` | `10` | Timeout on every broker call |
| `ADMIN_CACHE_TTL_SECONDS` | `5` | Shared cache, so N tabs cost one call |
| `ADMIN_POOL_SIZE` | `8` | Thread pool for blocking librdkafka calls |

## Logging and storage

| Variable | Default | Meaning |
|---|---|---|
| `LOG_LEVEL` | `INFO` | |
| `LOG_FORMAT` | `json` | `json` or `console` |
| `DATABASE_URL` | `sqlite:////data/offsetscope.db` | App state |

SQLite runs in WAL mode so the background sampler does not block API reads. Keep `/data` on a named volume. Credentials and tokens are redacted from logs by a processor, not by convention.

## Endpoints

| Path | Purpose |
|---|---|
| `/healthz` | Liveness. Never touches a broker |
| `/readyz` | Readiness: database, clusters, theme. `503` when not ready |
| `/api/docs` | OpenAPI documentation |
| `/api/openapi.json` | OpenAPI specification |

An unreachable broker is reported as a degraded state in the API and a banner in the UI — not a failed health check, because restarting the console cannot fix someone else's broker.
