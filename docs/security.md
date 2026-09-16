# Security and hardening

## Threat model

KafkaPlay is an operator tool. Anyone who can reach it and authenticate can read message data and, depending on role, change your cluster. Treat access to it as equivalent to broker credentials.

The console never phones home. Outbound connections go only to the Kafka clusters, Schema Registry, Prometheus, and notification targets you configure.

## Deployment checklist

- [ ] `SESSION_SECRET` set to a fresh 32+ character random value
- [ ] `ADMIN_PASSWORD` set, or the generated one retrieved from the logs and then changed
- [ ] `CONSOLE_BIND=127.0.0.1` unless a TLS reverse proxy is in front
- [ ] `SECURE_COOKIES=true` when served over HTTPS
- [ ] `READ_ONLY=true` if the console is for observation only
- [ ] `config/clusters.yaml` and `.env` excluded from git (both are ignored by default)
- [ ] Kafka credentials scoped to the least privilege the console needs
- [ ] `/data` on a named volume with a backup policy

## Least-privilege Kafka credentials

For a read-only console, the principal needs `Describe` and `Read` on topics and groups, plus `DescribeConfigs` on the cluster. Grant `Alter`, `Create`, `Delete` and `AlterConfigs` only if operators will use admin actions.

Pairing a read-only Kafka principal with `READ_ONLY=true` gives defence in depth: the console refuses the write, and the broker would refuse it too.

## Reverse proxy with TLS

```nginx
server {
    listen 443 ssl http2;
    server_name kafka-console.example.org;

    ssl_certificate     /etc/letsencrypt/live/kafka-console.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/kafka-console.example.org/privkey.pem;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSockets are used for live tail and live counters.
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
}
```

Set `SECURE_COOKIES=true` alongside this. Serving under a subpath additionally needs `ROOT_PATH=/your-path`.

## SSH tunnel

For a server with no public exposure, keep `CONSOLE_BIND=127.0.0.1` and tunnel:

```bash
ssh -L 8080:localhost:8080 user@server
```

Then browse to <http://127.0.0.1:8080>. Nothing is published to the network, and no TLS setup is needed because SSH provides the transport security.

## Session and CSRF handling

Sessions are signed cookies (`itsdangerous`), `HttpOnly` and `SameSite=Lax`, with a max age. There is no server-side session table, so rotating `SESSION_SECRET` logs everyone out at once.

CSRF uses a double-submit token: the signed cookie carries the expected value and the browser must echo it in an `X-CSRF-Token` header on every unsafe method. A cross-site form cannot set that header.

## OIDC

`AUTH_MODE=oidc` supports Keycloak, Google, GitHub, and Microsoft Entra, mapping a claim onto the `viewer` / `operator` / `admin` roles. Arrives in milestone 8.

## `AUTH_MODE=none`

Disables authentication entirely. Every visitor is an administrator.

It is refused on a non-loopback bind unless `ALLOW_INSECURE_NO_AUTH=true`, and the UI shows a permanent banner that cannot be dismissed. Inside Docker the app always binds `0.0.0.0`, so containerised use requires that acknowledgement explicitly.

Use it for local development only.

## Privacy and GDPR

Message data frequently contains personal data — IP addresses, emails, account identifiers.

- Masking is **on by default**, covering IPv4, IPv6, email, card-like numbers, and JWTs, with per-cluster and per-topic rules.
- **Message payloads are never written to disk.** They stream to the browser and are forgotten.
- Dashboard panel results are **ephemeral by default**. Persisting an aggregate is opt-in per panel, stores masked values only, and requires a retention window.
- Revealing a masked value is role-gated, and the audit log records that a reveal happened **without** storing the revealed value.
- The sampler stores offsets only — numbers, never content.

## Container hardening

The image runs as a non-root user (uid 10001), and the production compose file sets `read_only: true`, `no-new-privileges`, and a tmpfs for `/tmp`. Only `/data` is writable.

## Reporting a vulnerability

See [`SECURITY.md`](../SECURITY.md). Please do not open a public issue for security problems.
