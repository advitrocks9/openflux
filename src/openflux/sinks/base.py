"""Abstract sink interface"""

from __future__ import annotations

from abc import ABC, abstractmethod

from openflux.schema import Trace


class Sink(ABC):
    @abstractmethod
    def write(self, trace: Trace) -> None: ...

    @abstractmethod
    def close(self) -> None: ...
