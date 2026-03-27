"""LangChain / LangGraph adapter via BaseCallbackHandler."""

import importlib.util
import json
import threading
import time
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
        BaseCallbackHandler,
    )
else:
    BaseCallbackHandler = object


_DEFAULT_SEARCH_TOOLS: set[str] = {
    "web_search",
    "search_web",
    "search",
    "retrieve",
    "bing_search",
    "google_search",
    "tavily_search",
    "tavily_search_results_json",
    "duckduckgo_search",
    "serpapi",
    "searx_search",
}

_DEFAULT_FILE_READ_TOOLS: set[str] = {
    "read_file",
    "file_reader",
    "load_file",
    "read_document",
    "file_search",
}

_DEFAULT_FILE_WRITE_TOOLS: set[str] = {
    "write_file",
    "file_writer",
    "save_file",
    "create_file",
    "edit_file",
    "append_file",
}

# Generic chain names that don't provide useful scope information
_GENERIC_SCOPE_NAMES: set[str] = {
    "LangGraph",
    "RunnableSequence",
    "RunnableParallel",
    "RunnableLambda",
    "RunnablePassthrough",
    "RunnableBranch",
}


def _extract_last_human_message(messages: list[Any]) -> str:
    """Find the last human message content from a LangGraph messages list."""
    for msg in reversed(messages):
        # Handle tuples like ("human", "message text")
        if isinstance(msg, tuple) and len(msg) >= 2:
            if msg[0] == "human":
                return str(msg[1])[:2000]
            continue
        msg_type = getattr(msg, "type", None)
        # Messages can be dicts (serialized) or objects
        if msg_type is None and isinstance(msg, dict):
            msg_type = msg.get("type", "")
        if msg_type == "human":
            content = getattr(msg, "content", None)
            if content is None and isinstance(msg, dict):
                content = msg.get("content", "")
            if content:
                return str(content)[:2000]
    return ""


def _extract_final_ai_message(messages: list[Any]) -> str:
    """Find the last AI message without tool_calls (the final answer)."""
    for msg in reversed(messages):
        msg_type = getattr(msg, "type", None)
        if msg_type is None and isinstance(msg, dict):
            msg_type = msg.get("type", "")
        if msg_type != "ai":
            continue
        # Skip intermediate tool-calling messages
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls is None and isinstance(msg, dict):
            tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            continue
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content", "")
        if content:
            return str(content)[:4096]
    return ""


@dataclass(slots=True)
class _RunAccumulator:
    run_id: str
    parent_run_id: str | None = None
    started_at: str = ""
    started_at_mono: float = 0.0
    model: str = ""
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    tools: list[ToolRecord] = field(default_factory=lambda: list[ToolRecord]())
    searches: list[SearchRecord] = field(default_factory=lambda: list[SearchRecord]())
    sources: list[SourceRecord] = field(default_factory=lambda: list[SourceRecord]())
    context: list[ContextRecord] = field(default_factory=lambda: list[ContextRecord]())
    files_modified: list[str] = field(default_factory=lambda: list[str]())
    tags: list[str] = field(default_factory=lambda: list[str]())
    scope: str | None = None
    task: str = ""
    decision: str = ""
    metadata: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())
    has_error: bool = False
    # Dedup set for context records to avoid duplicate system_prompt entries
    seen_context_hashes: set[str] = field(default_factory=lambda: set[str]())


class OpenFluxCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler that accumulates events into Traces."""

    def __init__(
        self,
        agent: str = "langchain-agent",
        on_trace: Any | None = None,
        search_tools: set[str] | None = None,
        file_read_tools: set[str] | None = None,
        file_write_tools: set[str] | None = None,
        scope: str | None = None,
    ) -> None:
        super().__init__()
        self._agent = agent
        self._on_trace = on_trace
        self._search_tools = search_tools or _DEFAULT_SEARCH_TOOLS
        self._file_read_tools = file_read_tools or _DEFAULT_FILE_READ_TOOLS
        self._file_write_tools = file_write_tools or _DEFAULT_FILE_WRITE_TOOLS
        self._default_scope = scope
        self._lock = threading.Lock()
        self._runs: dict[str, _RunAccumulator] = {}
        self._completed: list[Trace] = []
        self._top_level_runs: set[str] = set()
        # Per-tool-run pending state: run_id -> (name, input, timestamp, mono)
        self._pending_tools: dict[str, tuple[str, str, str, float]] = {}

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
                    started_at_mono=time.monotonic(),
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
        self._get_or_create_run(run_id, parent_run_id)
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        ser_kwargs = (serialized or {}).get("kwargs", {})
        model = ser_kwargs.get("model_name", "") or ser_kwargs.get("model", "")
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
        self._get_or_create_run(run_id, parent_run_id)
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        ser_kwargs = (serialized or {}).get("kwargs", {})
        model = ser_kwargs.get("model_name", "") or ser_kwargs.get("model", "")
        if model:
            root.model = model

        # Also check invocation_params (used by some providers like Google)
        inv_params: dict[str, Any] = kwargs.get("invocation_params", {})
        inv_model = inv_params.get("model_name", "") or inv_params.get("model", "")
        if inv_model and not root.model:
            root.model = inv_model

        # Capture system prompts from message lists (dedup by content hash)
        for message_list in messages:
            for msg in message_list:
                msg_type: str = str(getattr(msg, "type", ""))
                if msg_type == "system":
                    content: str = str(getattr(msg, "content", ""))
                    if content:
                        chash = content_hash(content)
                        if chash in root.seen_context_hashes:
                            continue
                        root.seen_context_hashes.add(chash)
                        root.context.append(
                            ContextRecord(
                                type=ContextType.SYSTEM_PROMPT,
                                source="chat_model",
                                content_hash=chash,
                                content=content[:4096],
                                bytes=len(content.encode("utf-8")),
                                timestamp=utc_now(),
                            )
                        )

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._get_or_create_run(run_id, parent_run_id)
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        llm_output: dict[str, Any] = getattr(response, "llm_output", None) or {}

        # Try llm_output first (OpenAI-style providers)
        token_usage: dict[str, Any] = llm_output.get("token_usage", {})
        if token_usage:
            root.token_usage.input_tokens += int(token_usage.get("prompt_tokens", 0))
            root.token_usage.output_tokens += int(
                token_usage.get("completion_tokens", 0)
            )

        # Fallback: extract from generation message metadata (Google, Anthropic)
        if not token_usage:
            self._extract_tokens_from_generations(response, root)

        model: str = str(llm_output.get("model_name", ""))
        if model:
            root.model = model

        # Fallback: model from generation_info (Google providers)
        if not root.model:
            self._extract_model_from_generations(response, root)

        # LangGraph: capture tool_calls from AIMessage as reasoning metadata
        self._extract_tool_calls_from_generations(response, root)

    @staticmethod
    def _extract_tokens_from_generations(response: Any, root: _RunAccumulator) -> None:
        """Extract token counts from generation message usage_metadata."""
        generations: list[list[Any]] = getattr(response, "generations", [])
        for gen_list in generations:
            for gen in gen_list:
                msg = getattr(gen, "message", None)
                if msg is None:
                    continue
                usage = getattr(msg, "usage_metadata", None)
                if usage is None:
                    continue
                # LangChain UsageMetadata uses input_tokens/output_tokens
                usage_dict = (
                    usage if isinstance(usage, dict) else getattr(usage, "__dict__", {})
                )
                inp = int(usage_dict.get("input_tokens", 0))
                out = int(usage_dict.get("output_tokens", 0))
                if inp or out:
                    root.token_usage.input_tokens += inp
                    root.token_usage.output_tokens += out
                    return

    @staticmethod
    def _extract_model_from_generations(response: Any, root: _RunAccumulator) -> None:
        """Extract model name from generation_info or response_metadata."""
        generations: list[list[Any]] = getattr(response, "generations", [])
        for gen_list in generations:
            for gen in gen_list:
                # Check generation_info
                gen_info: dict[str, Any] = getattr(gen, "generation_info", {}) or {}
                model = gen_info.get("model_name", "")
                if model:
                    root.model = str(model)
                    return
                # Check message.response_metadata
                msg = getattr(gen, "message", None)
                if msg:
                    resp_meta: dict[str, Any] = (
                        getattr(msg, "response_metadata", {}) or {}
                    )
                    model = resp_meta.get("model_name", "")
                    if model:
                        root.model = str(model)
                        return

    @staticmethod
    def _extract_tool_calls_from_generations(
        response: Any, root: _RunAccumulator
    ) -> None:
        """Capture tool_calls from AIMessage as reasoning metadata."""
        generations: list[list[Any]] = getattr(response, "generations", [])
        for gen_list in generations:
            for gen in gen_list:
                msg = getattr(gen, "message", None)
                if msg is None:
                    continue
                tool_calls: list[Any] = getattr(msg, "tool_calls", [])
                if not tool_calls:
                    continue
                calls_list: list[dict[str, Any]] = root.metadata.setdefault(
                    "tool_calls", []
                )
                for tc in tool_calls:
                    # tool_calls can be dicts or objects with name/args attrs
                    if isinstance(tc, dict):
                        calls_list.append(
                            {"name": tc.get("name", ""), "args": tc.get("args", {})}
                        )
                    else:
                        calls_list.append(
                            {
                                "name": getattr(tc, "name", ""),
                                "args": getattr(tc, "args", {}),
                            }
                        )

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._get_or_create_run(run_id, parent_run_id)
        # Store per-tool-run so concurrent tools don't clobber each other
        key = str(run_id)
        self._pending_tools[key] = (
            (serialized or {}).get("name", ""),
            str(input_str)[:4096],
            utc_now(),
            time.monotonic(),
        )

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._get_or_create_run(run_id, parent_run_id)
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        # Per-tool-run state avoids clobbering when concurrent tools overlap
        key = str(run_id)
        pending = self._pending_tools.pop(key, None)
        tool_name = pending[0] if pending else ""
        tool_input = pending[1] if pending else ""
        tool_ts = pending[2] if pending else ""
        tool_mono = pending[3] if pending else 0.0
        tool_duration = int((time.monotonic() - tool_mono) * 1000) if tool_mono else 0

        # LangGraph passes ToolMessage objects, need .content for the string
        raw_output = str(getattr(output, "content", output))
        tool_output = raw_output[:16384]

        # Classify tool by name
        name_lower = tool_name.lower()
        if name_lower in self._search_tools:
            root.searches.append(
                SearchRecord(
                    query=tool_input[:500],
                    engine=tool_name,
                    timestamp=tool_ts,
                )
            )
        elif name_lower in self._file_read_tools:
            path = self._extract_path_from_input(tool_input)
            root.sources.append(
                SourceRecord(
                    type=SourceType.FILE,
                    path=path,
                    content_hash=content_hash(tool_output) if tool_output else "",
                    content=tool_output[:4096],
                    tool=tool_name,
                    bytes_read=len(tool_output.encode("utf-8")) if tool_output else 0,
                    timestamp=tool_ts,
                )
            )

        if name_lower in self._file_write_tools:
            path = self._extract_path_from_input(tool_input)
            if path and path not in root.files_modified:
                root.files_modified.append(path)

        root.tools.append(
            ToolRecord(
                name=tool_name,
                tool_input=tool_input,
                tool_output=tool_output,
                duration_ms=tool_duration,
                timestamp=tool_ts,
            )
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._get_or_create_run(run_id, parent_run_id)
        root = self._find_root_run(run_id) or self._get_or_create_run(
            run_id, parent_run_id
        )
        key = str(run_id)
        pending = self._pending_tools.pop(key, None)
        tool_name = pending[0] if pending else ""
        tool_input = pending[1] if pending else ""
        tool_ts = pending[2] if pending else ""
        tool_mono = pending[3] if pending else 0.0
        tool_duration = int((time.monotonic() - tool_mono) * 1000) if tool_mono else 0
        root.tools.append(
            ToolRecord(
                name=tool_name,
                tool_input=tool_input,
                tool_output=str(error)[:16384],
                error=True,
                duration_ms=tool_duration,
                timestamp=tool_ts,
            )
        )
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
        self._get_or_create_run(run_id, parent_run_id)
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
        self._get_or_create_run(run_id, parent_run_id)
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
        self._get_or_create_run(run_id, parent_run_id)
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
        self._get_or_create_run(run_id, parent_run_id)
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
        ser = serialized if isinstance(serialized, dict) else {}
        name = ser.get("name", "")
        # Skip generic framework names that don't convey useful scope
        is_useful_name = name and name not in _GENERIC_SCOPE_NAMES

        if is_useful_name and parent_run_id is not None:
            root = self._find_root_run(run_id)
            if root and root.scope is None:
                root.scope = name
        elif is_useful_name and parent_run_id is None and acc.scope is None:
            acc.scope = name
        elif parent_run_id is None and acc.scope is None and self._default_scope:
            # Fall back to user-provided default scope
            acc.scope = self._default_scope

        # Capture tags from kwargs (LangChain passes tags through callbacks)
        run_tags: list[str] = kwargs.get("tags", [])
        if run_tags and isinstance(run_tags, list):
            for tag in run_tags:
                if tag and tag not in acc.tags:
                    acc.tags.append(str(tag))

        if parent_run_id is None and not acc.task:
            if isinstance(inputs, dict):
                inp = inputs.get("input", inputs.get("question", ""))
                if inp:
                    acc.task = str(inp)[:2000]
                # LangGraph passes {"messages": [HumanMessage(...)]} instead
                elif "messages" in inputs:
                    acc.task = _extract_last_human_message(inputs["messages"])
            elif isinstance(inputs, list):
                # LangGraph may pass a list of message tuples directly
                acc.task = _extract_last_human_message(inputs)

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
                if isinstance(outputs, dict):
                    output = outputs.get("output", outputs.get("answer", ""))
                    if output and not acc.decision:
                        acc.decision = str(output)[:4096]
                    # LangGraph: final answer is last AIMessage without tool_calls
                    if not acc.decision and "messages" in outputs:
                        acc.decision = _extract_final_ai_message(outputs["messages"])
                elif not acc.decision:
                    # Non-dict output (e.g. str, AIMessage from LLM)
                    content = getattr(outputs, "content", None)
                    if content is not None:
                        # AIMessage/HumanMessage — use .content
                        text = str(content).strip()
                    else:
                        text = str(outputs).strip()
                    if text:
                        acc.decision = text[:4096]
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

    @staticmethod
    def _extract_path_from_input(tool_input: str) -> str:
        """Best-effort extraction of a file path from tool input."""
        path_keys = ("file_path", "path", "filename", "file", "name")
        # Try JSON first (common for structured tool calls)
        try:
            data = json.loads(tool_input)
            if isinstance(data, dict):
                for key in path_keys:
                    val = data.get(key)
                    if val and isinstance(val, str):
                        return val
        except (json.JSONDecodeError, TypeError):
            pass
        # LangGraph often passes Python repr strings (single quotes)
        import ast

        try:
            data = ast.literal_eval(tool_input)
            if isinstance(data, dict):
                for key in path_keys:
                    val = data.get(key)
                    if val and isinstance(val, str):
                        return val
        except (ValueError, SyntaxError):
            pass
        # Fall back to raw string if it looks like a path
        stripped = tool_input.strip()
        if "/" in stripped or stripped.startswith("."):
            return stripped[:500]
        return ""

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
        duration = (
            int((time.monotonic() - acc.started_at_mono) * 1000)
            if acc.started_at_mono
            else 0
        )
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
            tags=acc.tags,
            context=acc.context,
            searches=acc.searches,
            sources_read=acc.sources,
            tools_used=acc.tools,
            files_modified=acc.files_modified,
            turn_count=len(acc.tools),
            token_usage=acc.token_usage,
            duration_ms=duration,
            metadata=acc.metadata,
        )

    def _write_default_sink(self, trace: Trace) -> None:
        import os

        try:
            from openflux.sinks.sqlite import SQLiteSink

            db_env = os.environ.get("OPENFLUX_DB_PATH", "")
            sink = SQLiteSink(path=db_env) if db_env else SQLiteSink()
            sink.write(trace)
            sink.close()
        except Exception:
            pass

    @property
    def completed_traces(self) -> list[Trace]:
        with self._lock:
            return list(self._completed)
