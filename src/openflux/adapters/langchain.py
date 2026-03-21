"""LangChain / LangGraph adapter via BaseCallbackHandler."""

import importlib.util
import threading
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from openflux._util import content_hash, generate_trace_id, utc_now
from openflux.schema import (
    ContextRecord,
    ContextType,
    SearchRecord,
    SourceRecord,
    SourceType,
    Status,
    TokenUsage,
    ToolRecord,
    Trace,
)

_HAS_LANGCHAIN = importlib.util.find_spec("langchain_core") is not None

if _HAS_LANGCHAIN:
    from langchain_core.callbacks import (
        # type: ignore[import-untyped],
        BaseCallbackHandler,
)
else:
    BaseCallbackHandler = object  # type: ignore[assignment,misc]


@dataclass(slots=True)
class _RunAccumulator:
    run_id: str
    parent_run_id: str | None = None
    started_at: str = ""
    model: str = ""
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    tools: list[ToolRecord] = field(default_factory=lambda: list[ToolRecord]())
    searches: list[SearchRecord] = field(default_factory=lambda: list[SearchRecord]())
    sources: list[SourceRecord] = field(default_factory=lambda: list[SourceRecord]())
    context: list[ContextRecord] = field(default_factory=lambda: list[ContextRecord]())
    files_modified: list[str] = field(default_factory=lambda: list[str]())
    scope: str | None = None
    task: str = ""
    decision: str = ""
    metadata: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())
    has_error: bool = False
    pending_tool_name: str = ""
    pending_tool_input: str = ""
    pending_tool_timestamp: str = ""


class OpenFluxCallbackHandler(BaseCallbackHandler):  # type: ignore[misc]
    """LangChain callback handler that accumulates events into Traces."""

    def __init__(
        self,
        agent: str = "langchain-agent",
        on_trace: Any | None = None,
    ) -> None:
        super().__init__()  # type: ignore[reportUnknownMemberType]
        self._agent = agent
        self._on_trace = on_trace
        self._lock = threading.Lock()
        self._runs: dict[str, _RunAccumulator] = {}
        self._completed: list[Trace] = []
        self._top_level_runs: set[str] = set()

    def _get_or_create_run(
        self,
        run_id: UUID,
        parent_run_id: UUID | None = None,
    ) -> _RunAccumulator:
        key = str(run_id)
        with self._lock:
            if key not in self._runs:
                acc = _RunAccumulator(
                    run_id=key,
                    parent_run_id=str(parent_run_id) if parent_run_id else None,
                    started_at=utc_now(),
                )
                self._runs[key] = acc
                if parent_run_id is None:
                    self._top_level_runs.add(key)
            return self._runs[key]

    def _find_root_run(self, run_id: UUID) -> _RunAccumulator | None:
        key = str(run_id)
        visited: set[str] = set()
        with self._lock:
            while key and key not in visited:
                visited.add(key)
                acc = self._runs.get(key)
                if acc is None:
                    return None
                if acc.parent_run_id is None or key in self._top_level_runs:
                    return acc
                key = acc.parent_run_id
        return None

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        model = serialized.get("kwargs", {}).get("model_name", "")
        if model:
            root.model = model

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        model = serialized.get("kwargs", {}).get("model_name", "")
        if model:
            root.model = model

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        llm_output: dict[str, Any] = getattr(response, "llm_output", None) or {}
        token_usage: dict[str, Any] = llm_output.get("token_usage", {})
        if token_usage:
            root.token_usage.input_tokens += int(token_usage.get("prompt_tokens", 0))
            root.token_usage.output_tokens += int(
                token_usage.get("completion_tokens", 0)
            )

        model: str = str(llm_output.get("model_name", ""))
        if model:
            root.model = model

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        root.pending_tool_name = serialized.get("name", "")
        root.pending_tool_input = str(input_str)[:4096]
        root.pending_tool_timestamp = utc_now()

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        root.tools.append(
            ToolRecord(
                name=root.pending_tool_name,
                tool_input=root.pending_tool_input,
                tool_output=str(output)[:16384],
                timestamp=root.pending_tool_timestamp,
            )
        )
        root.pending_tool_name = ""
        root.pending_tool_input = ""
        root.pending_tool_timestamp = ""

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        root.tools.append(
            ToolRecord(
                name=root.pending_tool_name,
                tool_input=root.pending_tool_input,
                tool_output=str(error)[:16384],
                error=True,
                timestamp=root.pending_tool_timestamp,
            )
        )
        root.pending_tool_name = ""
        root.pending_tool_input = ""
        root.pending_tool_timestamp = ""
        root.has_error = True

    def on_retriever_start(
        self,
        serialized: dict[str, Any],
        query: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        root.searches.append(
            SearchRecord(
                query=query,
                engine=serialized.get("name", "retriever"),
                timestamp=utc_now(),
            )
        )

    def on_retriever_end(
        self,
        documents: list[Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        if root.searches:
            root.searches[-1].results_count = len(documents)

        for doc in documents:
            page_content: str = str(getattr(doc, "page_content", ""))
            doc_metadata: dict[str, Any] = getattr(doc, "metadata", {})
            source: str = str(doc_metadata.get("source", doc_metadata.get("url", "")))

            root.sources.append(
                SourceRecord(
                    type=SourceType.DOCUMENT,
                    path=source,
                    content_hash=(content_hash(page_content) if page_content else ""),
                    content=page_content[:4096],
                    tool="retriever",
                    bytes_read=(
                        len(page_content.encode("utf-8")) if page_content else 0
                    ),
                    timestamp=utc_now(),
                )
            )

            root.context.append(
                ContextRecord(
                    type=ContextType.RAG_CHUNK,
                    source=source,
                    content_hash=(content_hash(page_content) if page_content else ""),
                    content=page_content[:4096],
                    bytes=(len(page_content.encode("utf-8")) if page_content else 0),
                    timestamp=utc_now(),
                )
            )

    def on_agent_action(
        self,
        action: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        log: str = str(getattr(action, "log", ""))
        if log:
            reasoning: list[str] = root.metadata.setdefault("reasoning", [])
            reasoning.append(log[:2000])

    def on_agent_finish(
        self,
        finish: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        return_values: dict[str, Any] = getattr(finish, "return_values", {})
        output: str = str(return_values.get("output", ""))
        if output:
            root.decision = output[:4096]

        self._flush_run(root)

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        acc = self._get_or_create_run(run_id, parent_run_id)
        name = serialized.get("name", "")
        if name and parent_run_id is not None:
            root = self._find_root_run(run_id)
            if root and root.scope is None:
                root.scope = name

        if parent_run_id is None:
            inp = inputs.get("input", inputs.get("question", ""))
            if inp and not acc.task:
                acc.task = str(inp)[:2000]

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        key = str(run_id)
        if key in self._top_level_runs:
            with self._lock:
                acc = self._runs.get(key)
            if acc is not None:
                output = outputs.get("output", outputs.get("answer", ""))
                if output and not acc.decision:
                    acc.decision = str(output)[:4096]
                self._flush_run(acc)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        key = str(run_id)
        with self._lock:
            acc = self._runs.get(key)
        if acc is not None:
            acc.has_error = True

    def _flush_run(self, acc: _RunAccumulator) -> None:
        trace = self._build_trace(acc)

        with self._lock:
            self._completed.append(trace)
            self._runs.pop(acc.run_id, None)
            self._top_level_runs.discard(acc.run_id)

        if self._on_trace:
            self._on_trace(trace)
        else:
            self._write_default_sink(trace)

    def _build_trace(self, acc: _RunAccumulator) -> Trace:
        return Trace(
            id=generate_trace_id(),
            timestamp=acc.started_at or utc_now(),
            agent=self._agent,
            session_id=acc.run_id,
            parent_id=acc.parent_run_id,
            model=acc.model,
            task=acc.task,
            decision=acc.decision,
            status=Status.ERROR if acc.has_error else Status.COMPLETED,
            scope=acc.scope,
            context=acc.context,
            searches=acc.searches,
            sources_read=acc.sources,
            tools_used=acc.tools,
            files_modified=acc.files_modified,
            turn_count=len(acc.tools),
            token_usage=acc.token_usage,
            metadata=acc.metadata,
        )

    def _write_default_sink(self, trace: Trace) -> None:
        try:
            from openflux.sinks.sqlite import SQLiteSink

            sink = SQLiteSink()
            sink.write(trace)
            sink.close()
        except Exception:
            pass

    @property
    def completed_traces(self) -> list[Trace]:
        with self._lock:
            return list(self._completed)
