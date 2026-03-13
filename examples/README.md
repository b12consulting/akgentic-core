# Akgentic Examples

Hands-on examples demonstrating the Akgentic agent framework for Elixir/OTP.
Each example builds on the previous, introducing new concepts progressively.

## Prerequisites

```bash
# From the project root
mix deps.get
mix compile
```

## Running Examples

```bash
mix run examples/01_hello_world.exs
mix run examples/02_request_response.exs
mix run examples/03_dynamic_agents.exs
mix run examples/04_stateful_agents.exs
mix run examples/05_multi_agent.exs
mix run examples/06_agent_cards.exs
```

## Learning Path

| Example | Concept | Key APIs |
|---------|---------|----------|
| 01 Hello World | Defining actions and agents; pure functional `cmd/2` | `use Akgentic.Agent`, `use Jido.Action`, `cmd/2` |
| 02 Request/Response | Blocking vs fire-and-forget signal patterns | `Akgentic.signal/3`, `Akgentic.signal_async/3` |
| 03 Dynamic Agents | Spawning supervised agent processes at runtime | `Akgentic.start_agent/2`, `Akgentic.stop_agent/1` |
| 04 Stateful Agents | Typed state schema, clamping, Orchestrator tracking | `schema:`, `Akgentic.Orchestrator` |
| 05 Multi-Agent | Orchestrated pipeline, EventSubscriber, UserProxy | `Akgentic.Orchestrator`, `Akgentic.UserProxy`, `Akgentic.EventSubscriber` |
| 06 Agent Cards | Capability discovery and routing permissions | `Akgentic.AgentCard` |

## Concept Index

| Concept | Where to Look |
|---------|---------------|
| Defining a new agent | `01_hello_world.exs`, `03_dynamic_agents.exs` |
| Defining an action (state mutation) | All examples — `use Jido.Action` modules |
| Signal routes (signal → action mapping) | `signal_routes:` option in `use Akgentic.Agent` |
| Synchronous request-response | `Akgentic.signal/3` — `02_request_response.exs` |
| Fire-and-forget messaging | `Akgentic.signal_async/3` — `02_request_response.exs` |
| Dynamic agent spawning | `Akgentic.start_agent/2` — `03_dynamic_agents.exs` |
| Typed state with defaults | `schema:` option — `04_stateful_agents.exs` |
| Reading current state in an action | `context.agent.state` — `04_stateful_agents.exs` |
| Orchestrator telemetry | `Akgentic.Orchestrator.record_signal/2` — `04_stateful_agents.exs` |
| Multi-agent pipelines | `05_multi_agent.exs` |
| Human-in-the-loop | `Akgentic.UserProxy` — `05_multi_agent.exs` |
| Workflow event monitoring | `Akgentic.EventSubscriber` — `05_multi_agent.exs` |
| Agent capability discovery | `Akgentic.AgentCard`, `Akgentic.Orchestrator` catalog — `06_agent_cards.exs` |
| Routing permission checks | `AgentCard.can_route_to?/2` — `06_agent_cards.exs` |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     OTP Supervisor Tree                      │
│                                                             │
│  ┌──────────────────────┐    ┌────────────────────────┐    │
│  │ Akgentic.AgentSupervisor│   │ Akgentic.AgentRegistry │    │
│  │ (DynamicSupervisor)  │    │ (Registry)             │    │
│  └──────────┬───────────┘    └────────────────────────┘    │
│             │                                               │
│    ┌────────┼────────┐                                      │
│    ▼        ▼        ▼                                      │
│  [Agent1] [Agent2] [Agent3]  ← Jido.AgentServer processes   │
└─────────────────────────────────────────────────────────────┘

Signal Flow:
  Akgentic.signal(pid, "type", %{params}) 
    → Jido.AgentServer.call/2 
      → signal_routes lookup 
        → Jido.Action.run/2 
          → {:ok, state_updates}
            → agent.state merged with updates

Orchestrator Telemetry:
  Agent lifecycle + message events 
    → Orchestrator.record_signal/2 
      → EventSubscriber.on_message/1 callbacks
        → Timer inactivity tracking
```

## Python → Elixir Mapping

| Python (akgentic) | Elixir (Akgentic + Jido) |
|-------------------|--------------------------|
| `Akgent` (pykka.ThreadingActor) | `use Akgentic.Agent` (wraps `Jido.Agent`) |
| `receiveMsg_<Type>` handler | `signal_routes:` + `Jido.Action` |
| `self.send(recipient, msg)` | `Akgentic.signal/3` (sync) or `Akgentic.signal_async/3` (async) |
| `proxy_ask()` | `Akgentic.signal/3` (blocking, returns `{:ok, agent}`) |
| `proxy_tell()` | `Akgentic.signal_async/3` (fire-and-forget, returns `:ok`) |
| `self.createActor()` | `Akgentic.start_agent/2` |
| `ActorSystem` | OTP Supervisor + `Jido.AgentServer` |
| `BaseConfig` | `schema:` option in `use Akgentic.Agent` |
| `BaseState` | `agent.state` (Jido agent state fields) |
| `Orchestrator` | `Akgentic.Orchestrator` (GenServer) |
| `UserProxy` | `Akgentic.UserProxy` (GenServer) |
| `EventSubscriber` protocol | `Akgentic.EventSubscriber` behaviour |
| `AgentCard` | `Akgentic.AgentCard` struct |
| `Timer(threading.Timer)` | `Akgentic.Timer` (GenServer + `Process.send_after`) |
