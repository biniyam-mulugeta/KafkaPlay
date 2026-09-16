"""Container healthcheck.

Used by the image's HEALTHCHECK instruction. Kept as a script rather than an
inline one-liner so a failure reports one clear line instead of a urllib
traceback in `docker inspect` output.

Liveness only: it deliberately does not contact any broker. An unreachable
cluster is a degraded state reported through the API, not a reason for the
orchestrator to restart this container.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 4


def main() -> int:
    port = os.environ.get("CONSOLE_PORT", "8080")
    url = f"http://127.0.0.1:{port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            if response.status == 200:
                return 0
            print(f"unhealthy: {url} returned HTTP {response.status}", file=sys.stderr)
            return 1
    except urllib.error.HTTPError as exc:
        print(f"unhealthy: {url} returned HTTP {exc.code}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"unhealthy: cannot reach {url}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
