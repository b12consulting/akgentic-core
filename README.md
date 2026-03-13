# Akgentic Core: An Agent Framework powered by Jido

**Status:** Alpha - Phase 1 (Core Library)

## What is Akgentic Core?

Akgentic Core is an Elixir agent framework for building agent-based systems, powered by [Jido](https://jido.run/) and OTP. It provides zero-infrastructure-dependency agent primitives with comprehensive testability.

Agents are immutable data structures with pure functional state transformations, backed by OTP's battle-tested supervision and process model for production deployment.

## Quick Start

```elixir
# Define an action
defmodule MyApp.Actions.Echo do
  use Jido.Action,
    name: "echo",
    description: "Echoes a message",
    schema: [
      content: [type: :string, required: true]
    ]

  def run(params, _context) do
    IO.puts("Echo: #{params.content}")
    {:ok, %{last_echo: params.content}}
  end
end

# Define an agent
defmodule MyApp.EchoAgent do
  use Akgentic.Agent,
    name: "echo_agent",
    description: "An agent that echoes messages",
    schema: [
      last_echo: [type: :string, default: ""]
    ],
    actions: [MyApp.Actions.Echo],
    signal_routes: [
      {"echo", MyApp.Actions.Echo}
    ]
end

# Create and use the agent (pure data, no process needed)
agent = MyApp.EchoAgent.new()
{agent, _directives} = MyApp.EchoAgent.cmd(agent, {MyApp.Actions.Echo, %{content: "Hello!"}})
agent.state.last_echo
# => "Hello!"

# Or run with a process (production use)
{:ok, pid} = Akgentic.start_agent(MyApp.EchoAgent, id: "echo-1")
{:ok, agent} = Akgentic.signal(pid, "echo", %{content: "Hello, Akgentic!"})
```

## Design Principles

- **Pure functional agents** — Immutable state, deterministic logic, easy testing
- **Directive-based effects** — Side effects are described, not executed inline
- **Zero infrastructure dependencies** in core library
- **OTP supervision** — Fault-tolerant, self-healing agent processes
- **Comprehensive type specs** (Dialyzer compatible)

## Installation

Add `akgentic` to your dependencies in `mix.exs`:

```elixir
def deps do
  [
    {:akgentic, "~> 1.0.0-alpha.1"}
  ]
end
```

## Python → Elixir Migration Guide

This project was migrated from a Python actor framework (using Pykka) to Elixir using [Jido](https://jido.run/). Here's the concept mapping:

| Python (akgentic)       | Elixir (Akgentic + Jido)              |
|-------------------------|---------------------------------------|
| `Akgent`                | `Akgentic.Agent` (uses `Jido.Agent`)  |
| `Message`               | `Jido.Signal`                         |
| `receiveMsg_<Type>`     | `signal_routes` + `Jido.Action`       |
| `ActorSystem`           | OTP Supervisor + `Jido.AgentServer`   |
| `BaseConfig`            | Agent schema (NimbleOptions)          |
| `BaseState`             | Agent state                           |
| `Orchestrator`          | `Akgentic.Orchestrator`               |
| `UserProxy`             | `Akgentic.UserProxy`                  |
| `ActorAddress`          | PID / Registry lookup                 |
| `AgentCard`             | `Akgentic.AgentCard`                  |
| `EventSubscriber`       | `Akgentic.EventSubscriber` behaviour  |
| `ExecutionContext`      | Caller process                        |
| `ProxyWrapper`          | `Jido.AgentServer.call/cast`          |
| `Timer`                 | `Akgentic.Timer` (GenServer)          |

### Key Differences

1. **No `receiveMsg_<Type>` pattern** — In Jido, agents define `signal_routes` that map signal types to `Jido.Action` modules. Actions are pure functions that transform state.

2. **Immutable agents** — Python agents were mutable objects. Elixir agents are immutable data structures. State changes produce new agent values.

3. **Directives instead of `self.send()`** — Instead of sending messages directly, actions return directives (Emit, Spawn, Stop, etc.) that the runtime executes.

4. **OTP supervision** — Instead of manual `ActorSystem.shutdown()`, agents are supervised by OTP. Crashed agents restart automatically.

5. **No serialization boilerplate** — Elixir terms are natively serializable. Jido Signals use the CloudEvents spec.

## Development

### Prerequisites

- Elixir 1.17+
- Erlang/OTP 26+

### Setup

```bash
# Install dependencies
mix deps.get

# Run tests
mix test

# Type checking
mix dialyzer

# Linting
mix credo --strict

# All quality checks
mix quality
```

## Module Overview

| Module                         | Description                                        |
|--------------------------------|----------------------------------------------------|
| `Akgentic`                     | Top-level API for starting/signaling agents        |
| `Akgentic.Agent`               | Base agent macro wrapping `Jido.Agent`             |
| `Akgentic.Messages`            | Helper functions for creating common signals       |
| `Akgentic.Messages.Orchestrator` | Orchestrator telemetry signal types               |
| `Akgentic.Orchestrator`        | Telemetry and coordination GenServer               |
| `Akgentic.UserProxy`           | Human-in-the-loop agent                            |
| `Akgentic.AgentCard`           | Agent profile metadata for capability discovery    |
| `Akgentic.Timer`               | Inactivity timeout management                      |
| `Akgentic.EventSubscriber`     | Behaviour for subscribing to orchestrator events   |
| `Akgentic.Application`         | OTP Application with DynamicSupervisor             |

## Examples

Working examples are in [`examples/`](examples/):

```bash
mix run examples/01_hello_world.exs
```

## Architecture

- **Phase 1 (Current):** Core library with zero infrastructure dependencies
- **Phase 2 (Future):** LLM, tools, RAG modules (via `jido_ai`)
- **Phase 3 (Future):** Infrastructure plugins (persistence, pub/sub)

## License

See [LICENSE](LICENSE) for details.
