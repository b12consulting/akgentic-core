# 05 — Multi-Agent Coordination

> A coordinator routes tasks through a research-write-review pipeline, with a human-in-the-loop
> approval step — bringing together everything learned so far and introducing event subscribers
> and the `UserProxy`.

---

## Concepts introduced

### `UserProxy` — the human as an agent

In akgentic-core, a human is just another actor. `UserProxy` is a built-in base class that
represents a human participant in the system. It receives messages, "thinks" (in real usage this
means waiting for actual user input via a UI or CLI), and sends messages back.

Subclass it to define how your application bridges the actor system to a real human:

```python
from akgentic import UserProxy

class SimulatedUserProxy(UserProxy):

    def receiveMsg_ReviewRequest(self, message: ReviewRequest, sender: ActorAddress | None) -> None:
        # In a real app: display to user, await input, return response
        approval = ApprovalResponse(approved=True, feedback="Looks good!")
        if sender is not None:
            self.send(sender, approval)
```

The rest of the system doesn't need to change to add or remove a human from the loop — the
`UserProxy` is just another agent with an address.

---

### `OrchestratorEventSubscriber` — reacting to orchestrator events

The `Orchestrator` (introduced in [example 04](04-stateful-agents.md)) broadcasts events as
messages flow through the system. You can subscribe any object to receive these events by
implementing `OrchestratorEventSubscriber`:

```python
from akgentic import OrchestratorEventSubscriber

class SimpleLogger(OrchestratorEventSubscriber):

    def on_message(self, msg: Message) -> None:
        self.message_count += 1

    def on_state_changed(self, msg: Message) -> None:
        pass   # called whenever an agent fires notify_state_change()

    def on_llm_context_changed(self, msg: Message) -> None:
        pass   # called when an LLM agent's context window changes

    def on_tool_update(self, msg: Message) -> None:
        pass   # called when a tool is invoked

    def on_stop(self) -> None:
        pass   # called when the orchestrator shuts down
```

Register the subscriber via the orchestrator proxy:

```python
orch_proxy = actor_system.proxy_ask(orchestrator_addr, Orchestrator)
orch_proxy.subscribe(SimpleLogger())
```

Subscribers are the extension point for adding external integrations — databases, WebSockets,
dashboards — without modifying any agent logic.

---

### Full Orchestrator telemetry API

Once agents have been running, the Orchestrator accumulates a complete picture of the session.
You can query it at any point:

```python
team     = orch_proxy.get_team()      # { agent_id: AgentInfo }
messages = orch_proxy.get_messages()  # [ Message, ... ]  — all messages seen
states   = orch_proxy.get_states()    # { agent_id: StateSnapshot }
```

Together these give you: who is on the team, what was said, and what state each agent is in.

---

### Coordinator pattern

The `CoordinatorAgent` in this example is a pure router — it receives a message, updates its
own state to reflect the current workflow stage, and forwards the message to the next agent in
the pipeline. It never does domain work itself.

This separates **routing logic** from **domain logic**, making each specialist agent simpler and
independently testable.

---

## Message flow

```
main()      ActorSystem   Orchestrator  Coordinator  Researcher   Writer    UserProxy
  |              |             |             |            |          |           |
  |--create(O)-->|             |             |            |          |           |
  |              |--spawn----->|             |            |          |           |
  |              |             |             |            |          |           |
  |--subscribe(Logger)-------->|             |            |          |           |
  |              |             |             |            |          |           |
  |--create(R,W,U,C)---------->|             |            |          |           |
  |              |--spawn------|------------>|            |          |           |
  |              |--spawn------|-------------|----------->|          |           |
  |              |--spawn------|-------------|------------|--------->|           |
  |              |--spawn------|-------------|------------|----------|---------->|
  |              |             |             |            |          |           |
  |--tell(TaskRequest)---------|------------>|            |          |           |
  |              |             |             |            |          |           |
  |              |             |  receiveMsg_TaskRequest  |          |           |
  |              |             |<--state_change(researching)         |           |
  |              |             |             |--send(TaskRequest)--->|           |
  |              |             |             |            |          |           |
  |              |             |    receiveMsg_TaskRequest           |           |
  |              |             |<--state_change(research done)       |           |
  |              |             |             |<--send(ResearchResult)|           |
  |              |             |             |            |          |           |
  |              |             |  receiveMsg_ResearchResult          |           |
  |              |             |<--state_change(drafting) |          |           |
  |              |             |             |--send(ResearchResult)-|---------->|
  |              |             |             |            |          |           |
  |              |             |                receiveMsg_ResearchResult        |
  |              |             |<--state_change(draft done)          |           |
  |              |             |             |<--send(DraftContent)--|           |
  |              |             |             |            |          |           |
  |              |             |  receiveMsg_DraftContent |          |           |
  |              |             |<--state_change(reviewing)|          |           |
  |              |             |             |--send(ReviewRequest)--|---------->|
  |              |             |             |            |          |           |
  |              |             |                     receiveMsg_ReviewRequest    |
  |              |             |             |<--send(ApprovalResponse)----------|
  |              |             |             |            |          |           |
  |              |             |  receiveMsg_ApprovalResponse        |           |
  |              |             |<--state_change(done)     |          |           |
  |              |             |             |            |          |           |
  |--proxy_ask(get_team/messages/states)---->|            |          |           |
  |<--{ summary }--------------|             |            |          |           |
  |              |             |             |            |          |           |
  |--shutdown()-->|            |             |            |          |           |
```

---

## Walkthrough

This example assembles all previous concepts into a realistic pipeline:

**Setup**: The Orchestrator is created first, a `SimpleLogger` is subscribed to it, then all
specialist agents are started with a reference to the Orchestrator so their state changes are
tracked automatically.

**Routing**: The `CoordinatorAgent` holds references to all other agents and acts as the
switchboard. When a message arrives it updates its own `CoordinatorState` (stage: researching /
drafting / reviewing / done) and forwards the message on. Each stage transition is a
`notify_state_change()`, giving the Orchestrator a complete audit trail.

**The pipeline**:
```
TaskRequest → ResearchAgent → ResearchResult
           → WriterAgent   → DraftContent
           → UserProxy     → ApprovalResponse
           → Coordinator   → done
```

**Human-in-the-loop**: `SimulatedUserProxy` auto-approves in this demo. In a real application
you would block in `receiveMsg_ReviewRequest` until the user responds (e.g. wait on an asyncio
event, poll a database, or receive a WebSocket message), then send the `ApprovalResponse`.

**Post-run telemetry**: After the workflow completes, the Orchestrator can report the full
session summary:

```python
team     = orch_proxy.get_team()
messages = orch_proxy.get_messages()
states   = orch_proxy.get_states()

print(f"Total messages: {len(messages)}")
print(f"Team members:   {len(team)} agents")
print(f"State snapshots:{len(states)} agents tracked")
```

---

## Running it

```bash
uv run python examples/05_multi_agent.py
```

Expected output:

```
[Multi-Agent] Starting multi-agent coordination demo...
[Orchestrator] Team assembled: CoordinatorAgent, ResearchAgent, WriterAgent, UserProxy
[CoordinatorAgent] Routing task: "Write a summary of actor model benefits"
[ResearchAgent] Researching: "Write a summary of actor model benefits"
[ResearchAgent] Research complete: 3 key points found
[CoordinatorAgent] Received research, routing to WriterAgent
[WriterAgent] Drafting content from research...
[WriterAgent] Draft complete: 26 words
[CoordinatorAgent] Sending draft to UserProxy for human review
[UserProxy] Awaiting human input for review...
[UserProxy] Human approved the draft
[CoordinatorAgent] Task complete. Workflow finished.

=== Orchestrator Summary ===
Total messages: ...
Team members: 4 agents
State snapshots: 3 agents tracked
===========================
[Multi-Agent] Demo complete. Shutting down.
```

---

## You've reached the end of the core examples

You now have all the building blocks:

| Concept | Example |
|---|---|
| Messages, agents, actor system | [01](01-hello-world.md) |
| Bidirectional messaging, proxies | [02](02-request-response.md) |
| Dynamic spawning, parent-child | [03](03-dynamic-agents.md) |
| Typed state, observer, Orchestrator | [04](04-stateful-agents.md) |
| UserProxy, subscribers, full telemetry | 05 (this file) |

From here you can explore `akgentic-framework` to add LLM capabilities on top of these same
patterns.
