# Akgentic v2: Zero-Dependency Actor Framework

**Status:** Alpha - Phase 1 (Core Library)

## What is Akgentic v2?

Akgentic v2 is a Python 3.12+ actor framework for building agent-based systems with **zero infrastructure dependencies**.

Unlike v1 (which requires Redis, PostgreSQL, Weaviate), v2's core runs entirely in-memory with comprehensive testability.

## Quick Start

```python
# Coming soon - after Story 1.10 (Public API Exports)
from akgentic import ActorSystem, Agent, Message

# Create local actor system - zero infrastructure required
system = ActorSystem()
```

## Design Principles

- **Zero infrastructure dependencies** in core library
- **80% minimum test coverage** (enforced)
- **Comprehensive type hints** (mypy strict mode)
- **10-minute time-to-first-agent** target

## Development

```bash
# Install development dependencies
uv sync --dev

# Run tests
uv run pytest

# Type checking
uv run mypy src/

# Linting
uv run ruff check src/
```

## Architecture

Phase 1 (Current): Core library with zero dependencies
Phase 2 (Future): LLM, tools, RAG modules
Phase 3 (Future): Infrastructure plugins (Redis, HTTP, persistence)

## Migration from v1

See `docs/migration_guide.md` (coming soon)
