# Contributing to OpenFlux

## Setup

```bash
git clone https://github.com/advitrocks9/openflux.git
cd openflux
uv sync --group dev
```

## Development

Run tests:

```bash
uv run pytest tests/ -v
```

Lint and format:

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

Type check:

```bash
uv run pyright src/
```

## Pull Requests

Before opening a PR, make sure:

- `uv run pytest tests/ -v` passes
- `uv run ruff check src/ tests/` is clean
- `uv run ruff format --check src/ tests/` is clean
- `uv run pyright src/` reports no errors

## Writing Adapters

Each adapter lives in its own file under `src/openflux/adapters/`. Follow the pattern in existing adapters:

1. Guard framework imports with `try/except ImportError` so the core package stays zero-dep.
2. Hook into the framework's callback or event system.
3. Emit raw event dicts to the normalizer -- don't do classification or hashing yourself.
4. Add the framework as an optional dependency in `pyproject.toml` under `[project.optional-dependencies]`.
5. Add tests in `tests/` that mock the framework dependency.
