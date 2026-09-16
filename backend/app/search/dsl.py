"""The message filter DSL.

JMESPath, evaluated server-side against a record shaped as:

    {
      "key":     <decoded key>,
      "value":   <decoded value>,
      "headers": {"name": "value", ...},
      "topic":   "orders",
      "partition": 3,
      "offset":  12345,
      "timestamp": 1758000000000
    }

So a filter reads naturally:

    value.status == 'failed'
    value.amount_cents > `10000`
    contains(value.path, '/admin')
    headers.source == 'gateway' && value.score > `0.9`

JMESPath rather than a bespoke language: it is a published spec, safe to
evaluate (no code execution), and already familiar to anyone who has used the
AWS CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jmespath
from jmespath.exceptions import JMESPathError
from jmespath.parser import ParsedResult


class FilterError(ValueError):
    """The expression could not be compiled."""


@dataclass(slots=True)
class MessageFilter:
    expression: str
    _compiled: ParsedResult

    @classmethod
    def compile(cls, expression: str) -> MessageFilter:
        text = expression.strip()
        if not text:
            raise FilterError("filter expression is empty")
        try:
            return cls(expression=text, _compiled=jmespath.compile(text))
        except JMESPathError as exc:
            raise FilterError(f"invalid filter expression: {exc}") from exc

    def matches(self, record: dict[str, Any]) -> bool:
        """Evaluate the filter against one record.

        Truthiness follows JMESPath: null, false, empty string, empty list and
        empty object are false. An expression that errors on a particular
        record (a missing field, a type mismatch) is treated as "no match"
        rather than aborting the whole scan, because real topics contain
        heterogeneous records.
        """
        try:
            result = self._compiled.search(record)
        except JMESPathError:
            return False
        except Exception:
            return False
        return bool(result)


def validate_filter(expression: str) -> str | None:
    """Return an error message, or None when the expression compiles."""
    try:
        MessageFilter.compile(expression)
    except FilterError as exc:
        return str(exc)
    return None
