# Akgentic Core: An Actor Based Agent Framework

**Status:** Alpha - Phase 1 (Core Library)

## What is Akgentic Core?

Akgentic Core is a Python 3.12+ actor framework for building agent-based systems with **zero infrastructure dependencies** (no dependency to database, event broker, ...).

Akgentic Core runs entirely in-memory with comprehensive testability.

## Quick Start

```python
from akgentic import ActorAddress, ActorSystem, Akgent
from akgentic.messages import Message


# Define a simple message class
class EchoMessage(Message):
    content: str


# Define a simple agent that echoes messages
class EchoAgent(Akgent):
    def receiveMsg_EchoMessage(self, message: EchoMessage, sender: ActorAddress) -> None:
        print(f"EchoAgent received: {message.content}")


# Create local actor system
system = ActorSystem()

# Create an agent instance
agent = system.createActor(EchoAgent)

# Send a message to the agent
system.tell(agent, EchoMessage(content="Hello, Akgentic!"))

system.shutdown()
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

## Examples

Working examples are in [`examples/`](examples/) — each one is self-contained and runnable.

### How to Run

```bash
# From the akgentic-core directory
uv run python examples/01_hello_world.py
uv run python examples/02_request_response.py
uv run python examples/03_dynamic_agents.py
uv run python examples/04_stateful_agents.py
uv run python examples/05_multi_agent.py
```

### Learning Path

Work through them in order — each builds on the previous and introduces a small set of new concepts.

| #   | Description                                                                            | Guide                                                    |
| --- | -------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| 01  | Two agents exchange a greeting — introduces `Message`, `Akgent`, and `ActorSystem`     | [01 — Hello World](examples/01-hello-world.md)           |
| 02  | `proxy_tell` (fire-and-forget) vs `proxy_ask` (blocking) with request-response pairing | [02 — Request-Response](examples/02-request-response.md) |
| 03  | A manager spawns worker agents at runtime — parent-child hierarchy and `createActor()` | [03 — Dynamic Agents](examples/03-dynamic-agents.md)     |
| 04  | Typed state across messages, observer pattern, and Orchestrator telemetry              | [04 — Stateful Agents](examples/04-stateful-agents.md)   |
| 05  | Multi-agent pipeline with human-in-the-loop approval and event subscribers             | [05 — Multi-Agent](examples/05-multi-agent.md)           |

See [`examples/README.md`](examples/README.md) for the full concept index.

## Architecture

Phase 1 (Current): Core library with zero dependencies
Phase 2 (Future): LLM, tools, RAG modules
Phase 3 (Future): Infrastructure plugins (Redis, HTTP, persistence)

## Migration from v1

See `docs/migration_guide.md` (coming soon)
