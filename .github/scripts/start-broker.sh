#!/usr/bin/env bash
#
# Starts a single-node broker on localhost:9092 for the integration matrix.
# Apache Kafka (KRaft) and Redpanda need different startup arguments, so the
# difference is handled here rather than in the workflow.
set -euo pipefail

IMAGE="${1:?usage: start-broker.sh <image> <name>}"
NAME="${2:-broker}"

echo "Starting ${NAME} from ${IMAGE}"

case "${IMAGE}" in
  *redpanda*)
    docker run -d --name test-broker -p 9092:9092 -p 9644:9644 "${IMAGE}" \
      redpanda start \
        --overprovisioned \
        --smp 1 \
        --memory 1G \
        --reserve-memory 0M \
        --node-id 0 \
        --check=false \
        --kafka-addr PLAINTEXT://0.0.0.0:9092 \
        --advertise-kafka-addr PLAINTEXT://localhost:9092
    ;;
  *)
    docker run -d --name test-broker -p 9092:9092 \
      -e KAFKA_NODE_ID=1 \
      -e KAFKA_PROCESS_ROLES=broker,controller \
      -e KAFKA_LISTENERS='PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093' \
      -e KAFKA_ADVERTISED_LISTENERS='PLAINTEXT://localhost:9092' \
      -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
      -e KAFKA_CONTROLLER_QUORUM_VOTERS='1@localhost:9093' \
      -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP='CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT' \
      -e KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT \
      -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
      -e KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1 \
      -e KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1 \
      -e KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS=0 \
      -e KAFKA_AUTO_CREATE_TOPICS_ENABLE=false \
      "${IMAGE}"
    ;;
esac

# Poll the Kafka protocol itself rather than the port, so we do not start
# testing against a broker that is listening but not yet serving metadata.
python - <<'PY'
import sys
import time

from confluent_kafka.admin import AdminClient

deadline = time.time() + 180
admin = AdminClient({"bootstrap.servers": "localhost:9092"})
last = None
while time.time() < deadline:
    try:
        metadata = admin.list_topics(timeout=5)
        print(f"broker ready: {len(metadata.brokers)} broker(s)")
        sys.exit(0)
    except Exception as exc:
        last = exc
        time.sleep(3)
print(f"broker never became ready: {last}", file=sys.stderr)
sys.exit(1)
PY
