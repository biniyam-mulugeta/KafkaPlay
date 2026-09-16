"""Schema Registry client.

Confluent-compatible, which covers Confluent Cloud, Karapace (Aiven) and
Redpanda's registry. Read-only apart from compatibility checks, because the
console is not the right place to author schemas -- that belongs in the
producing service's build.

Protobuf decoding is handled by codecs/protobuf; this module deals with the
registry itself.
"""

from __future__ import annotations

import base64
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.clusters.models import SchemaRegistryConfig
from app.logging import get_logger

log = get_logger(__name__)


class SchemaType(StrEnum):
    AVRO = "AVRO"
    JSON = "JSON"
    PROTOBUF = "PROTOBUF"


class CompatibilityLevel(StrEnum):
    BACKWARD = "BACKWARD"
    BACKWARD_TRANSITIVE = "BACKWARD_TRANSITIVE"
    FORWARD = "FORWARD"
    FORWARD_TRANSITIVE = "FORWARD_TRANSITIVE"
    FULL = "FULL"
    FULL_TRANSITIVE = "FULL_TRANSITIVE"
    NONE = "NONE"


class SchemaVersion(BaseModel):
    subject: str
    version: int
    id: int
    schema_type: SchemaType = SchemaType.AVRO
    schema_text: str = ""
    references: list[dict[str, Any]] = Field(default_factory=list)


class SubjectSummary(BaseModel):
    name: str
    latest_version: int | None = None
    versions: list[int] = Field(default_factory=list)
    compatibility: str | None = None


class SchemaRegistryError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class SchemaRegistryClient:
    def __init__(self, config: SchemaRegistryConfig, *, timeout: float = 10.0) -> None:
        self._config = config
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.schemaregistry.v1+json, application/json"}
        if self._config.username and self._config.password:
            token = base64.b64encode(
                f"{self._config.username}:{self._config.password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {token}"
        return headers

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._config.url.rstrip("/"),
            timeout=self._timeout,
            headers=self._headers(),
            verify=not self._config.insecure_skip_verify,
        )

    async def _get(self, path: str) -> Any:
        try:
            async with self._client() as client:
                response = await client.get(path)
        except httpx.HTTPError as exc:
            raise SchemaRegistryError(f"schema registry is unreachable: {exc}") from exc

        if response.status_code == 404:
            raise SchemaRegistryError("not found in the schema registry", status_code=404)
        if response.status_code >= 400:
            raise SchemaRegistryError(
                f"schema registry returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
        return response.json()

    async def list_subjects(self) -> list[str]:
        result = await self._get("/subjects")
        return sorted(str(item) for item in result) if isinstance(result, list) else []

    async def list_versions(self, subject: str) -> list[int]:
        result = await self._get(f"/subjects/{subject}/versions")
        return sorted(int(item) for item in result) if isinstance(result, list) else []

    async def get_version(self, subject: str, version: int | str = "latest") -> SchemaVersion:
        payload = await self._get(f"/subjects/{subject}/versions/{version}")
        return SchemaVersion(
            subject=payload.get("subject", subject),
            version=int(payload.get("version", 0)),
            id=int(payload.get("id", 0)),
            schema_type=SchemaType(payload.get("schemaType", "AVRO")),
            schema_text=payload.get("schema", ""),
            references=payload.get("references", []) or [],
        )

    async def get_by_id(self, schema_id: int) -> SchemaVersion:
        payload = await self._get(f"/schemas/ids/{schema_id}")
        return SchemaVersion(
            subject="",
            version=0,
            id=schema_id,
            schema_type=SchemaType(payload.get("schemaType", "AVRO")),
            schema_text=payload.get("schema", ""),
            references=payload.get("references", []) or [],
        )

    async def compatibility(self, subject: str) -> str | None:
        """The subject's compatibility level, falling back to the global one."""
        try:
            payload = await self._get(f"/config/{subject}")
        except SchemaRegistryError as exc:
            if exc.status_code != 404:
                return None
            try:
                payload = await self._get("/config")
            except SchemaRegistryError:
                return None
        value = payload.get("compatibilityLevel") or payload.get("compatibility")
        return str(value) if value else None

    async def check_compatibility(
        self, subject: str, schema_text: str, schema_type: SchemaType = SchemaType.AVRO
    ) -> tuple[bool, list[str]]:
        """Test a candidate schema against the subject's latest version.

        This is a read-only check: the registry evaluates it without
        registering anything.
        """
        body = {"schema": schema_text, "schemaType": str(schema_type)}
        try:
            async with self._client() as client:
                response = await client.post(
                    f"/compatibility/subjects/{subject}/versions/latest?verbose=true",
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise SchemaRegistryError(f"schema registry is unreachable: {exc}") from exc

        if response.status_code >= 400:
            raise SchemaRegistryError(
                f"schema registry returned HTTP {response.status_code}: {response.text[:400]}",
                status_code=response.status_code,
            )

        payload = response.json()
        return bool(payload.get("is_compatible", False)), list(payload.get("messages", []) or [])

    async def summarise(self, subject: str) -> SubjectSummary:
        versions = await self.list_versions(subject)
        return SubjectSummary(
            name=subject,
            versions=versions,
            latest_version=versions[-1] if versions else None,
            compatibility=await self.compatibility(subject),
        )
