# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-03-23

### Added

- Core schema (Trace) with 22 fields and 4 nested record types
- Normalizer with fidelity modes and path exclusion
- Thread-safe collector
- SQLite sink with FTS5 search
- NDJSON stdout sink
- OTLP/HTTP export sink
- 9 framework adapters (Claude Code, OpenAI Agents SDK, LangChain, Claude Agent SDK, AutoGen, CrewAI, Google ADK, MCP, Bedrock)
- CLI with recent, search, trace, export, status, install commands
