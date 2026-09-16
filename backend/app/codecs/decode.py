"""Decoding message keys and values.

Kafka stores bytes and says nothing about their meaning, so the console has to
guess. The order matters: Schema Registry framing is checked first because it
is unambiguous, then JSON, then UTF-8 text, and finally a hex view.

A decode failure is never an error -- it falls through to the next strategy and
ultimately to hex, so the browser always shows something.
"""

from __future__ import annotations

import binascii
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PayloadFormat(StrEnum):
    NULL = "null"
    JSON = "json"
    AVRO = "avro"
    PROTOBUF = "protobuf"
    TEXT = "text"
    BINARY = "binary"


@dataclass(slots=True)
class DecodedPayload:
    format: PayloadFormat
    value: Any
    """Decoded value: an object for JSON/Avro, a string for text, hex for binary."""

    size_bytes: int
    schema_id: int | None = None
    error: str | None = None
    """Set when a schema-framed payload could not be decoded."""


# Confluent wire format: magic byte 0, then a 4-byte big-endian schema id.
_MAGIC = 0
_FRAMING_LENGTH = 5


def looks_schema_framed(data: bytes) -> bool:
    return len(data) > _FRAMING_LENGTH and data[0] == _MAGIC


def framed_schema_id(data: bytes) -> int | None:
    if not looks_schema_framed(data):
        return None
    return int.from_bytes(data[1:5], "big")


def to_hex(data: bytes, *, limit: int = 2048) -> str:
    """Hex view, truncated so a large binary payload cannot flood the browser."""
    clipped = data[:limit]
    text = binascii.hexlify(clipped, " ").decode("ascii")
    if len(data) > limit:
        text += f" … (+{len(data) - limit} bytes)"
    return text


def decode_json(data: bytes) -> Any | None:
    """Parse JSON, but only accept container types.

    A bare number or the word `null` is valid JSON yet is far more likely to
    be plain text in a Kafka payload, so those fall through to the text
    strategy where they display more naturally.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def decode_text(data: bytes) -> str | None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    # Control characters other than whitespace mean this is really binary.
    if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in text):
        return None
    return text


def decode_payload(
    data: bytes | None,
    *,
    schema_decoder: Any | None = None,
) -> DecodedPayload:
    """Decode a key or value into the best representation available.

    ``schema_decoder`` is an optional object with
    ``decode(data, schema_id) -> (value, format)``; when absent, schema-framed
    payloads are reported as binary with their schema id, which is still more
    useful than raw bytes.
    """
    if data is None:
        return DecodedPayload(format=PayloadFormat.NULL, value=None, size_bytes=0)

    size = len(data)
    if size == 0:
        return DecodedPayload(format=PayloadFormat.TEXT, value="", size_bytes=0)

    schema_id = framed_schema_id(data)
    if schema_id is not None:
        if schema_decoder is not None:
            try:
                value, fmt = schema_decoder.decode(data, schema_id)
                return DecodedPayload(format=fmt, value=value, size_bytes=size, schema_id=schema_id)
            except Exception as exc:
                # Show the hex and say why, rather than an empty cell.
                return DecodedPayload(
                    format=PayloadFormat.BINARY,
                    value=to_hex(data),
                    size_bytes=size,
                    schema_id=schema_id,
                    error=f"schema decode failed: {exc}",
                )
        return DecodedPayload(
            format=PayloadFormat.BINARY,
            value=to_hex(data),
            size_bytes=size,
            schema_id=schema_id,
            error="no Schema Registry configured for this cluster",
        )

    parsed = decode_json(data)
    if parsed is not None:
        return DecodedPayload(format=PayloadFormat.JSON, value=parsed, size_bytes=size)

    text = decode_text(data)
    if text is not None:
        return DecodedPayload(format=PayloadFormat.TEXT, value=text, size_bytes=size)

    return DecodedPayload(format=PayloadFormat.BINARY, value=to_hex(data), size_bytes=size)
