# 04 — Stateful Agents

> A counter agent maintains typed state across messages, notifies an Orchestrator on every
> change, and exposes the full audit trail — introducing state management and telemetry.

---

## Concepts introduced

### `BaseState` — typed agent state

Every `Akgent` carries a `state` field. By default it is a plain `BaseState`, but you can
subclass it to add your own fields:

```python
from akgentic import BaseState

class CounterState(BaseState):
    count: int = 0
    history: list[str] = []
    last_operation: str = ""
```

The type parameter on `Akgent[Config, StateType]` tells the framework which state type this
agent uses:

```python
class CounterAgent(Akgent[BaseConfig, CounterState]):
    ...
```

State lives **inside** the agent and is never shared directly with other agents.

---

### Observer pattern — `state.observer()` and `notify_state_change()`

State changes are invisible to the outside world by default. The observer pattern lets you
broadcast them. In `init()`, attach the agent itself as an observer of its own state:

```python
def init(self) -> None:
    super().init()
    self.state = CounterState()
    self.state.observer(self)   # subscribe to state change events
```

After mutating state in a handler, call `notify_state_change()` to fire the event:

```python
def receiveMsg_IncrementMessage(self, message: IncrementMessage, sender: ActorAddress | None) -> None:
    self.state.count += message.amount
    self.state.history.append(message.label)
    self.state.last_operation = f"Incremented by {message.amount}"
    self.state.notify_state_change()   # broadcast the change
```

The observer pattern decouples the agent from anything that wants to track its state — the agent
simply announces "I changed"; it doesn't need to know who is listening.

---

### Orchestrator — telemetry hub

The `Orchestrator` is a built-in agent that listens for state change events and stores a
snapshot of each agent's state. It acts as a lightweight telemetry hub without coupling agents
to each other:

```python
from akgentic import Orchestrator

orchestrator_addr = actor_system.createActor(
    Orchestrator,
    config=BaseConfig(name="orchestrator", role="Orchestrator"),
)
```

Pass the orchestrator address when starting an agent so it can report to it:

```python
counter_ref = CounterAgent.start(
    ...
    orchestrator=orchestrator_addr,
)
```

After the workflow completes, query the Orchestrator through a proxy:

```python
orch_proxy = actor_system.proxy_ask(orchestrator_addr, Orchestrator)
states = orch_proxy.get_states()   # { agent_id: StateSnapshot }
```

---

## Message flow

```
main()            ActorSystem         Orchestrator         CounterAgent
  |                   |                   |                    |
  |--createActor(O)-->|                   |                    |
  |                   |--spawn----------->|                    |
  |                   |                   |                    |
  |--CounterAgent.start(orchestrator=O)-->|                    |
  |                   |--spawn------------|------------------- >|
  |                   |                   |                    |
  |--tell(Increment +5)------------------|-------------------->|
  |                   |                   |                    |
  |                   |             receiveMsg_IncrementMessage |
  |                   |                   |<--notify_state_change()
  |                   |                   |  (StateChangedMsg) |
  |                   |  on_state_changed |                    |
  |                   |                   |                    |
  |--tell(Increment +3)------------------|-------------------->|
  |                   |                   |<--notify_state_change()
  |                   |                   |                    |
  |--tell(Reset)-------------------------|-------------------->|
  |                   |                   |<--notify_state_change()
  |                   |                   |                    |
  |--tell(Increment +10)-----------------|-------------------->|
  |                   |                   |<--notify_state_change()
  |                   |                   |                    |
  |--proxy_ask(get_states)-------------->|                    |
  |<--{ counter_id: CounterState }-------|                    |
  |                   |                   |                    |
  |--shutdown()------>|                   |                    |
```

---

## Walkthrough

The counter agent maintains a `CounterState` with three fields: a running `count`, a `history`
list (one entry per operation), and `last_operation`. After every mutation it fires
`notify_state_change()`, which the Orchestrator intercepts and records.

At the end, you can retrieve a snapshot of the final state:

```python
states = orch_proxy.get_states()
if states:
    final = next(iter(states.values()))
    print(f"count={final.count}, history={final.history}")
```

The Orchestrator never needs to know about `CounterState` specifically — it stores whatever
`BaseState` subclass the agent reports. This makes it reusable across any agent type.

The combination of typed state + observer + Orchestrator gives you a full audit trail of an
agent's lifecycle without modifying the agent's core logic.

---

## Running it

```bash
uv run python examples/04_stateful_agents.py
```

Expected output:

```
[Stateful Agents] Demonstrating state management with Orchestrator tracking...
[CounterAgent] Incremented by 5 → count: 5 (label: "first increment")
[CounterAgent] Incremented by 3 → count: 8 (label: "second increment")
[CounterAgent] Reset → count: 0 (reason: "starting new sequence")
[CounterAgent] Incremented by 10 → count: 10 (label: "after reset")
[Orchestrator] Tracked 4 state changes for CounterAgent
[Orchestrator] Final state: count=10, history=['first increment', 'second increment', 'starting new sequence', 'after reset']
[Stateful Agents] State management demo complete.
```

---

## What's next

→ [05 — Multi-Agent](05-multi-agent.md): full multi-agent workflow with a human-in-the-loop and
   event subscribers.
