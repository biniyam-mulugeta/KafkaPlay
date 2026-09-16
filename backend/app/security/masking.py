"""Masking of sensitive values in message payloads.

On by default. Message data routinely contains personal data -- IP addresses,
emails, account identifiers -- and this console is pointed at production.

Two things this module guarantees:

1. Masking happens in the backend, before data is serialised to the browser.
   A UI toggle would leave the real values in the network response.
2. Revealing is a separate, role-gated action that is audited. The audit
   records *that* a reveal happened, never the revealed value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any

import jmespath

from app.clusters.models import MaskPreset, MaskRule

# Presets cover the categories that show up in real log and event streams.
# Each keeps a recognisable prefix so operators can still correlate records
# without seeing the whole value.
_IPV4 = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")
_IPV6 = re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{1,4}\b")
_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
# 13-19 digits, optionally separated, which covers the common card formats.
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")


def _mask_ipv4(match: re.Match[str]) -> str:
    octets = [match.group(i) for i in range(1, 5)]
    if any(int(octet) > 255 for octet in octets):
        return match.group(0)  # not actually an address
    return f"{octets[0]}.{octets[1]}.{octets[2]}.xxx"


def _luhn(digits: str) -> bool:
    """Only mask numbers that could really be card numbers.

    Without this, order ids and timestamps get mangled, which destroys the
    usefulness of the message browser.
    """
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _mask_card(match: re.Match[str]) -> str:
    raw = match.group(0)
    digits = re.sub(r"[ -]", "", raw)
    if not (13 <= len(digits) <= 19) or not _luhn(digits):
        return raw
    return f"{'*' * (len(digits) - 4)}{digits[-4:]}"


_PRESET_PATTERNS: dict[MaskPreset, tuple[re.Pattern[str], Any]] = {
    MaskPreset.IPV4: (_IPV4, _mask_ipv4),
    MaskPreset.IPV6: (_IPV6, lambda m: m.group(0).rsplit(":", 2)[0] + ":xxxx:xxxx"),
    MaskPreset.EMAIL: (_EMAIL, lambda m: f"{m.group(1)}***{m.group(2)}"),
    MaskPreset.CREDIT_CARD: (_CARD, _mask_card),
    MaskPreset.JWT: (_JWT, lambda m: "eyJ***.***.***"),
}


@dataclass(frozen=True, slots=True)
class MaskResult:
    value: Any
    """The masked payload."""

    applied: bool
    """Whether anything was actually changed."""


class Masker:
    """Applies a cluster's mask rules to decoded message payloads."""

    def __init__(self, rules: list[MaskRule], *, enabled: bool = True) -> None:
        self._enabled = enabled
        self._rules = rules
        self._compiled: list[tuple[MaskRule, re.Pattern[str], Any]] = []
        for rule in rules:
            if rule.preset is not None:
                pattern, replacement = _PRESET_PATTERNS[rule.preset]
            elif rule.pattern is not None:
                try:
                    pattern = re.compile(rule.pattern)
                except re.error:
                    # A bad regex in config must not break message browsing.
                    continue
                replacement = rule.replacement or "***"
            else:
                continue
            if rule.replacement is not None and rule.preset is not None:
                replacement = rule.replacement
            self._compiled.append((rule, pattern, replacement))

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._compiled)

    def _rules_for_topic(self, topic: str) -> list[tuple[re.Pattern[str], Any]]:
        active = []
        for rule, pattern, replacement in self._compiled:
            if rule.topics and not any(fnmatch(topic, glob) for glob in rule.topics):
                continue
            active.append((pattern, replacement))
        return active

    def _mask_text(self, text: str, rules: list[tuple[re.Pattern[str], Any]]) -> str:
        for pattern, replacement in rules:
            text = pattern.sub(replacement, text)
        return text

    def _walk(self, value: Any, rules: list[tuple[re.Pattern[str], Any]]) -> Any:
        if isinstance(value, str):
            return self._mask_text(value, rules)
        if isinstance(value, dict):
            return {key: self._walk(item, rules) for key, item in value.items()}
        if isinstance(value, list):
            return [self._walk(item, rules) for item in value]
        return value

    def mask(self, value: Any, *, topic: str = "") -> MaskResult:
        """Mask every string inside a decoded payload."""
        if not self.enabled:
            return MaskResult(value=value, applied=False)

        rules = self._rules_for_topic(topic)
        if not rules:
            return MaskResult(value=value, applied=False)

        path_rules = [
            (rule, pattern, replacement)
            for rule, pattern, replacement in self._compiled
            if rule.paths and (not rule.topics or any(fnmatch(topic, g) for g in rule.topics))
        ]

        # Path-scoped rules replace only the nodes they select; everything else
        # is masked wholesale.
        if path_rules:
            masked = value
            for rule, pattern, replacement in path_rules:
                for path in rule.paths:
                    try:
                        found = jmespath.search(path, masked)
                    except Exception:
                        continue
                    if isinstance(found, str):
                        masked = _set_path(masked, path, pattern.sub(replacement, found))
            broad = [
                (pattern, replacement)
                for rule, pattern, replacement in self._compiled
                if not rule.paths
                and (not rule.topics or any(fnmatch(topic, g) for g in rule.topics))
            ]
            if broad:
                masked = self._walk(masked, broad)
            return MaskResult(value=masked, applied=masked != value)

        masked = self._walk(value, rules)
        return MaskResult(value=masked, applied=masked != value)


def _set_path(data: Any, path: str, new_value: str) -> Any:
    """Set a dotted JMESPath location. Only simple field paths are supported."""
    parts = path.split(".")
    if not parts or not isinstance(data, dict):
        return data
    # Shallow copy down the path so the original payload is never mutated.
    result = dict(data)
    cursor = result
    for part in parts[:-1]:
        nxt = cursor.get(part)
        if not isinstance(nxt, dict):
            return data
        nxt = dict(nxt)
        cursor[part] = nxt
        cursor = nxt
    if parts[-1] in cursor:
        cursor[parts[-1]] = new_value
    return result


def build_masker(rules: list[MaskRule], *, cluster_enabled: bool, global_enabled: bool) -> Masker:
    """Masking is on unless both the cluster and the deployment turn it off."""
    return Masker(rules, enabled=cluster_enabled and global_enabled)
