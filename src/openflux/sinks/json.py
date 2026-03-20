"""NDJSON stdout sink"""

from __future__ import annotations

import json
import sys
from typing import override

from openflux.schema import Trace
from openflux.sinks.base import Sink


class JSONSink(Sink):
    @override
    def write(self, trace: Trace) -> None:
        line = json.dumps(trace.to_dict(), separators=(",", ":"), default=str)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    @override
    def close(self) -> None:
        pass
