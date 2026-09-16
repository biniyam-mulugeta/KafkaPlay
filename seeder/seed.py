"""Development data seeder.

Creates a small set of generic topics and keeps them fed, so every console
feature has something realistic to show:

  orders        JSON, keyed, 6 partitions      -- the general-purpose topic
  clickstream   JSON with a user_agent field   -- skewed keys, for the heatmap
  app-logs      plain text, no schema          -- exercises non-JSON rendering
  payments      Avro via Schema Registry       -- exercises schema decoding
  audit-trail   JSON, replication factor 1     -- so under-replication warnings
                                                  have something to report

It also runs two consumer groups: one that keeps up, and one that reads slowly
on purpose so lag, lag velocity, and time-to-catch-up are never empty charts.

Nothing here is specific to any real deployment; it is demo data.
"""

from __future__ import annotations

import io
import json
import logging
import os
import random
import signal
import string
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from types import FrameType

import fastavro
import requests
from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [seeder] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("seeder")

BOOTSTRAP = os.environ.get("BOOTSTRAP_SERVERS", "kafka:9092")
SCHEMA_REGISTRY = os.environ.get("SCHEMA_REGISTRY_URL", "http://schema-registry:8081")
RATE = max(1, int(os.environ.get("EVENTS_PER_SECOND", "25")))

_stop = threading.Event()

TOPICS = [
    NewTopic("orders", num_partitions=6, replication_factor=1),
    NewTopic("clickstream", num_partitions=3, replication_factor=1),
    NewTopic("app-logs", num_partitions=2, replication_factor=1),
    NewTopic("payments", num_partitions=3, replication_factor=1),
    NewTopic("audit-trail", num_partitions=1, replication_factor=1),
]

PAYMENT_SCHEMA = {
    "type": "record",
    "name": "Payment",
    "namespace": "dev.kafkaplay",
    "fields": [
        {"name": "payment_id", "type": "string"},
        {"name": "amount_cents", "type": "long"},
        {"name": "currency", "type": "string"},
        {"name": "status", "type": "string"},
        {"name": "created_at", "type": "string"},
    ],
}

REGIONS = ["eu-central", "eu-west", "us-east", "ap-south"]
STATUSES = ["created", "paid", "refunded", "failed"]
PAGES = ["/", "/search", "/product", "/cart", "/checkout", "/account"]
AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/141.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0 Safari/537.36",
    "curl/8.5.0",
]
LEVELS = ["DEBUG", "INFO", "INFO", "INFO", "WARN", "ERROR"]


def wait_for_broker(timeout_seconds: int = 120) -> AdminClient:
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP})
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            admin.list_topics(timeout=5)
            log.info("broker reachable at %s", BOOTSTRAP)
            return admin
        except Exception as exc:  # broker not up yet
            log.info("waiting for broker: %s", exc)
            time.sleep(3)
    raise SystemExit(f"broker at {BOOTSTRAP} never became reachable")


def ensure_topics(admin: AdminClient) -> None:
    existing = set(admin.list_topics(timeout=10).topics)
    missing = [topic for topic in TOPICS if topic.topic not in existing]
    if not missing:
        log.info("topics already present")
        return
    for name, future in admin.create_topics(missing).items():
        try:
            future.result()
            log.info("created topic %s", name)
        except Exception as exc:
            log.warning("could not create %s: %s", name, exc)


def register_payment_schema() -> None:
    """Register the Avro schema so the console can decode `payments`."""
    url = f"{SCHEMA_REGISTRY}/subjects/payments-value/versions"
    for _ in range(20):
        try:
            response = requests.post(
                url,
                json={"schema": json.dumps(PAYMENT_SCHEMA), "schemaType": "AVRO"},
                headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
                timeout=5,
            )
            if response.ok:
                log.info("registered payments-value schema id=%s", response.json().get("id"))
                return
            log.warning("schema registry said %s: %s", response.status_code, response.text)
        except requests.RequestException as exc:
            log.info("waiting for schema registry: %s", exc)
        time.sleep(3)
    log.warning("giving up on schema registration; payments will show as binary")


def payment_schema_id() -> int | None:
    try:
        response = requests.get(f"{SCHEMA_REGISTRY}/subjects/payments-value/versions/latest", timeout=5)
        if response.ok:
            return int(response.json()["id"])
    except (requests.RequestException, KeyError, ValueError):
        pass
    return None


def encode_avro(record: dict[str, object], schema_id: int) -> bytes:
    """Confluent wire format: magic byte 0, 4-byte schema id, then Avro."""
    buffer = io.BytesIO()
    buffer.write(b"\x00")
    buffer.write(schema_id.to_bytes(4, "big"))
    fastavro.schemaless_writer(buffer, PAYMENT_SCHEMA, record)
    return buffer.getvalue()


def random_ip() -> str:
    # Documentation ranges only (RFC 5737) -- never a real routable address.
    return random.choice(["192.0.2", "198.51.100", "203.0.113"]) + f".{random.randint(1, 254)}"


def produce_forever() -> None:
    producer = Producer({"bootstrap.servers": BOOTSTRAP, "client.id": "kafkaplay-seeder"})
    schema_id = payment_schema_id()
    # A deliberately skewed key space so one partition runs hot and the
    # partition heatmap has something worth looking at.
    hot_customers = [f"cust-{i:03d}" for i in range(5)]
    all_customers = hot_customers + [f"cust-{i:03d}" for i in range(5, 200)]

    interval = 1.0 / RATE
    while not _stop.is_set():
        now = datetime.now(UTC).isoformat()
        customer = random.choice(hot_customers if random.random() < 0.6 else all_customers)

        producer.produce(
            "orders",
            key=customer.encode(),
            value=json.dumps(
                {
                    "order_id": str(uuid.uuid4()),
                    "customer_id": customer,
                    "region": random.choice(REGIONS),
                    "status": random.choice(STATUSES),
                    "total_cents": random.randint(500, 90_000),
                    "items": random.randint(1, 8),
                    "created_at": now,
                }
            ).encode(),
        )

        producer.produce(
            "clickstream",
            key=customer.encode(),
            value=json.dumps(
                {
                    "session_id": "".join(random.choices(string.hexdigits.lower(), k=16)),
                    "customer_id": customer,
                    "page": random.choice(PAGES),
                    "user_agent": random.choice(AGENTS),
                    "client_ip": random_ip(),
                    "dwell_ms": random.randint(80, 30_000),
                    "at": now,
                }
            ).encode(),
        )

        level = random.choice(LEVELS)
        producer.produce(
            "app-logs",
            value=f"{now} {level} worker-{random.randint(1, 4)} handled request in "
            f"{random.randint(2, 900)}ms".encode(),
        )

        if random.random() < 0.3:
            producer.produce(
                "audit-trail",
                key=customer.encode(),
                value=json.dumps(
                    {"actor": customer, "action": random.choice(["login", "update", "delete"]), "at": now}
                ).encode(),
            )

        if schema_id is not None and random.random() < 0.5:
            producer.produce(
                "payments",
                key=customer.encode(),
                value=encode_avro(
                    {
                        "payment_id": str(uuid.uuid4()),
                        "amount_cents": random.randint(100, 50_000),
                        "currency": random.choice(["EUR", "HUF", "USD"]),
                        "status": random.choice(STATUSES),
                        "created_at": now,
                    },
                    schema_id,
                ),
            )

        producer.poll(0)
        time.sleep(interval)

    producer.flush(10)


def consume_forever(group_id: str, topics: list[str], delay_seconds: float) -> None:
    """A consumer group. A non-zero delay makes it fall behind on purpose."""
    consumer = Consumer(
        {
            "bootstrap.servers": BOOTSTRAP,
            "group.id": group_id,
            "client.id": f"{group_id}-worker",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
        }
    )
    consumer.subscribe(topics)
    try:
        while not _stop.is_set():
            message = consumer.poll(1.0)
            if message is None or message.error():
                continue
            if delay_seconds:
                time.sleep(delay_seconds)
    finally:
        consumer.close()


def handle_signal(_signum: int, _frame: FrameType | None) -> None:
    log.info("shutting down")
    _stop.set()


def main() -> None:
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    admin = wait_for_broker()
    ensure_topics(admin)
    register_payment_schema()

    threads = [
        threading.Thread(target=produce_forever, name="producer", daemon=True),
        # Keeps up comfortably.
        threading.Thread(
            target=consume_forever,
            args=("order-processor", ["orders"], 0.0),
            name="consumer-fast",
            daemon=True,
        ),
        # Deliberately slow: this is what makes the lag features demonstrable.
        threading.Thread(
            target=consume_forever,
            args=("analytics-lagging", ["orders", "clickstream"], 0.25),
            name="consumer-slow",
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    log.info("seeding at ~%s events/sec; 'analytics-lagging' will fall behind on purpose", RATE)
    while not _stop.is_set():
        time.sleep(1)
    for thread in threads:
        thread.join(timeout=15)


if __name__ == "__main__":
    main()
