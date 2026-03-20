"""Pluggable output sinks for Trace objects"""

from openflux.sinks.base import Sink
from openflux.sinks.json import JSONSink
from openflux.sinks.otlp import OTLPSink
from openflux.sinks.sqlite import SQLiteSink

__all__ = ["Sink", "SQLiteSink", "JSONSink", "OTLPSink"]
