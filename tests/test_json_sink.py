from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

from conftest import make_trace

from openflux.sinks.json import JSONSink


class TestNDJSONOutput:
    def test_single_write(self) -> None:
        buf = StringIO()
        with patch("sys.stdout", buf):
            sink = JSONSink()
            sink.write(make_trace(task="hello"))
        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["task"] == "hello"

    def test_multiple_writes(self) -> None:
        buf = StringIO()
        with patch("sys.stdout", buf):
            sink = JSONSink()
            sink.write(make_trace(task="first"))
            sink.write(make_trace(task="second"))
            sink.write(make_trace(task="third"))
        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 3
        assert [json.loads(line)["task"] for line in lines] == [
            "first",
            "second",
            "third",
        ]
