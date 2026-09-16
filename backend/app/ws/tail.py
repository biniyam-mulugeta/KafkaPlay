"""Live tail over WebSocket.

Streams new messages from a topic as they arrive, with the filter applied
server-side and a rate limit so a busy topic cannot flood the browser.

The consumer is torn down when the socket closes -- including on an abrupt
disconnect -- so a closed tab never leaves a consumer running against the
broker.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.api.v1.messages import to_model
from app.codecs.decode import decode_payload
from app.kafka.errors import KafkaGateError, translate_kafka_error
from app.kafka.gate import build_client_config
from app.logging import get_logger
from app.search.dsl import FilterError, MessageFilter
from app.search.scan import ScannedMessage, _headers_to_dict, _record_for_filter
from app.security.masking import build_masker

router = APIRouter()
log = get_logger(__name__)

# Upper bound on what we will push per second, whatever the client asks for.
MAX_RATE = 200
DEFAULT_RATE = 20


@router.websocket("/ws/tail/{cluster}/{topic}")
async def tail_topic(
    websocket: WebSocket,
    cluster: str,
    topic: str,
    filter_expression: str | None = Query(default=None, alias="filter"),
    rate: int = Query(default=DEFAULT_RATE, ge=1, le=MAX_RATE),
) -> None:
    settings = websocket.app.state.settings
    registry = websocket.app.state.registry

    # Authentication: the session cookie rides along with the WebSocket
    # handshake, so the same signed cookie protects this as the REST API.
    if not settings.is_no_auth:
        token = websocket.cookies.get(settings.session_cookie_name)
        session = websocket.app.state.session_codec.loads(token) if token else None
        if session is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="not authenticated")
            return

    try:
        config = registry.get(cluster)
    except KeyError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="unknown cluster")
        return

    message_filter = None
    if filter_expression:
        try:
            message_filter = MessageFilter.compile(filter_expression)
        except FilterError as exc:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc))
            return

    masker = build_masker(
        config.mask_rules,
        cluster_enabled=config.masking_enabled,
        global_enabled=settings.masking_enabled,
    )

    await websocket.accept()
    stop = asyncio.Event()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)

    def consume() -> None:
        """Blocking consumer loop, run in a worker thread."""
        from confluent_kafka import Consumer, TopicPartition

        client_config = build_client_config(config, settings.admin_timeout_seconds)
        client_config.update(
            {
                "group.id": f"kafkaplay-tail-{int(time.time() * 1000)}",
                "enable.auto.commit": False,
                "auto.offset.reset": "latest",
            }
        )
        consumer = Consumer(client_config)
        try:
            metadata = consumer.list_topics(topic=topic, timeout=10)
            topic_meta = metadata.topics.get(topic)
            if topic_meta is None or not topic_meta.partitions:
                raise KafkaGateError(f"topic {topic!r} does not exist")

            # Start at the end of every partition: a tail shows what happens
            # from now on, not history.
            assignments = []
            for partition in sorted(topic_meta.partitions):
                _, high = consumer.get_watermark_offsets(
                    TopicPartition(topic, partition), timeout=10
                )
                assignments.append(TopicPartition(topic, partition, high))
            consumer.assign(assignments)

            interval = 1.0 / rate
            last_sent = 0.0

            while not stop.is_set():
                record = consumer.poll(0.5)
                if record is None or record.error() is not None:
                    continue

                now = time.monotonic()
                if now - last_sent < interval:
                    # Rate limit by dropping, not buffering: a live tail should
                    # show current traffic, not fall behind it.
                    continue
                last_sent = now

                record_partition = record.partition()
                record_offset = record.offset()
                if record_partition is None or record_offset is None:
                    continue

                timestamp_type, timestamp = record.timestamp()
                message = ScannedMessage(
                    topic=record.topic() or topic,
                    partition=record_partition,
                    offset=record_offset,
                    timestamp=timestamp if timestamp > 0 else None,
                    timestamp_type={
                        0: "not_available",
                        1: "create_time",
                        2: "log_append_time",
                    }.get(timestamp_type),
                    key=decode_payload(record.key()),
                    value=decode_payload(record.value()),
                    headers=_headers_to_dict(record.headers()),
                )

                if message_filter is not None and not message_filter.matches(
                    _record_for_filter(message)
                ):
                    continue

                if masker.enabled:
                    masked_value = masker.mask(message.value.value, topic=message.topic)
                    masked_key = masker.mask(message.key.value, topic=message.topic)
                    message.value.value = masked_value.value
                    message.key.value = masked_key.value
                    message.masked = masked_value.applied or masked_key.applied

                payload = json.loads(to_model(message).model_dump_json())
                # Browser cannot keep up: drop rather than grow the queue.
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(payload)
        except Exception as exc:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait({"_error": translate_kafka_error(exc).message})
        finally:
            with contextlib.suppress(Exception):
                consumer.close()

    loop = asyncio.get_running_loop()
    worker = loop.run_in_executor(None, consume)

    async def pump() -> None:
        while not stop.is_set():
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            await websocket.send_json(payload)

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            # The client sends "pause"/"resume"/"stop"; any disconnect raises.
            command = await websocket.receive_text()
            if command == "stop":
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("tail_socket_error", error=str(exc))
    finally:
        stop.set()
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task
        with contextlib.suppress(Exception):
            await worker
        with contextlib.suppress(Exception):
            await websocket.close()
