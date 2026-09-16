"""Load ``clusters.yaml`` with ``${ENV_VAR}`` substitution.

Secrets belong in the environment, not in the YAML file, so the file can be
committed or mounted from a ConfigMap while passwords arrive separately.

Supported forms:
    ${VAR}            -- required; a missing VAR is a startup error
    ${VAR:-fallback}  -- optional, with a default
    $${literal}       -- an escaped, literal "${literal}"
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.clusters.models import ClustersFile

# $${...} escape, or ${NAME} / ${NAME:-default}
_PATTERN = re.compile(
    r"""
    (?P<escaped>\$\$\{[^}]*\})
    |
    \$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}
    """,
    re.VERBOSE,
)


class ClusterConfigError(Exception):
    """Raised for an unreadable, malformed, or under-specified cluster file."""


def substitute_env(raw: str, environ: dict[str, str] | None = None) -> str:
    """Expand ``${VAR}`` references in ``raw``.

    Raises ``ClusterConfigError`` listing *every* missing variable at once,
    so an operator fixes their deployment in one pass rather than five.
    """
    env = os.environ if environ is None else environ
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        escaped = match.group("escaped")
        if escaped is not None:
            return escaped[1:]  # "$${x}" -> "${x}"
        name = match.group("name")
        if name in env:
            return env[name]
        default = match.group("default")
        if default is not None:
            return default
        missing.append(name)
        return ""

    result = _PATTERN.sub(replace, raw)
    if missing:
        unique = sorted(set(missing))
        raise ClusterConfigError(
            "clusters.yaml references environment variables that are not set: "
            + ", ".join(unique)
            + ". Set them, or give them defaults with ${NAME:-default}."
        )
    return result


def parse_clusters(raw: str, environ: dict[str, str] | None = None) -> ClustersFile:
    """Parse cluster YAML text into a validated model."""
    expanded = substitute_env(raw, environ)
    try:
        data: Any = yaml.safe_load(expanded)
    except yaml.YAMLError as exc:
        raise ClusterConfigError(f"clusters.yaml is not valid YAML: {exc}") from exc

    if data is None:
        return ClustersFile(clusters=[])
    if not isinstance(data, dict):
        raise ClusterConfigError(
            "clusters.yaml must be a mapping with a top-level 'clusters:' key, "
            f"got {type(data).__name__}"
        )

    try:
        return ClustersFile.model_validate(data)
    except ValidationError as exc:
        raise ClusterConfigError(f"clusters.yaml failed validation:\n{exc}") from exc


def load_clusters_file(path: Path, environ: dict[str, str] | None = None) -> ClustersFile:
    """Read and validate the cluster file.

    A missing file is not fatal: the console starts empty and an admin can add
    a cluster from the UI. That is the intended first-run experience for
    ``docker run`` with no config mounted.
    """
    if not path.exists():
        return ClustersFile(clusters=[])
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ClusterConfigError(f"cannot read {path}: {exc}") from exc
    return parse_clusters(raw, environ)
