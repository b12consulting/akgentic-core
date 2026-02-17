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

    def receiveMsg_ReviewRequest(self, message: ReviewRequest, sender: ActorAddress) -> None:
        # In a real app: display to user, await input, return response
        approval = ApprovalResponse(approved=True, feedback="Looks good!")
        self.send(sender, approval)
```

The rest of the system doesn't need to change to add or remove a human from the loop — the
`UserProxy` is just another agent with an address.

**Connecting an external system (frontend, API, CLI):** when the agent workflow reaches the
`UserProxy` and is waiting for a human decision, your external system calls
`process_human_input()` on the proxy — obtained via `actor_system.proxy_ask(user_proxy_addr, UserProxy)`:

```python
user_proxy = actor_system.proxy_ask(user_proxy_addr, UserProxy)

# Called by your frontend / REST handler / CLI when the human responds:
user_proxy.process_human_input(
    content="Approved — publish it.",
    message=original_review_request,   # the message the UserProxy received
)
```

The default implementation wraps the human's response in a `ResultMessage` and sends it to
`message.sender` — routing the reply back into the agent pipeline without any other wiring.

Override `process_human_input` in a subclass to add validation, logging, or custom routing
before the response is dispatched:

```python
class ValidatingUserProxy(UserProxy):
    def process_human_input(self, content: str, message: Message) -> None:
        if content.strip() not in ("approve", "reject"):
            raise ValueError(f"Unexpected input: {content!r}")
        super().process_human_input(content, message)
```

---

### `OrchestratorEventSubscriber` — reacting to orchestrator events

The `Orchestrator` (introduced in [example 04](04-stateful-agents.md)) broadcasts events as
messages flow through the system. You can subscribe any object to receive these events by
implementing `OrchestratorEventSubscriber`:

```python
from akgentic import OrchestratorEventSubscriber

class SimpleLogger(OrchestratorEventSubscriber):

    def on_message(self, msg: Message) -> None:
        # msg is one of the agent lifecycle telemetry types:
        #   StartMessage      — agent started
        #   StopMessage       — agent stopped
        #   SentMessage       — agent sent a message to another agent
        #   ReceivedMessage   — agent received a message
        #   ProcessedMessage  — agent finished processing a message
        #   ErrorMessage      — agent raised an error while processing
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

### Team formation via `createActor()`

All agents in a session must be created through `proxy_ask(orchestrator).createActor()` — never
via the pykka-internal `.start()` class method directly.

When `orch_proxy.createActor(SomeAgent, config=...)` is called:

- The orchestrator's own `createActor` implementation calls `.start()` internally
- `team_id`, `user_id`, `user_email`, `parent`, and `orchestrator` are propagated from the
  orchestrator's own context into the new child agent
- The new agent announces itself via `StartMessage` to the orchestrator on startup

This is what `get_team()` uses to enumerate team members — it scans `StartMessage` history to
find all agents that reported to this orchestrator.

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
main()         ActorSystem    Orchestrator   Coordinator   Researcher    Writer     UserProxy
  |                 |              |              |             |           |            |
  |-createActor(O)->|              |              |             |           |            |
  |                 |--spawn------>|              |             |           |            |
  |--proxy_ask(O)-->|         orch_proxy          |             |           |            |
  |--subscribe(Logger)------------>|              |             |           |            |
  |                 |              |              |             |           |            |
  |--orch_proxy.createActor(R)---->|              |             |           |            |
  |                 |              |--spawn------>|------------>|           |            |
  |--orch_proxy.createActor(W)---->|              |             |           |            |
  |                 |              |--spawn------>|-------------|---------->|            |
  |--orch_proxy.createActor(U)---->|              |             |           |            |
  |                 |              |--spawn------>|-------------|-----------|----------->|
  |--orch_proxy.createActor(C)---->|              |             |           |            |
  |                 |              |--spawn------>|             |           |            |
  |                 |              | (team_id, orchestrator, parent: auto-propagated)   |
  |--proxy_tell(C)->|              |              |             |           |            |
  |                 |--set_agents(R,W,U)--------->|             |           |            |
  |                 |              |              |             |           |            |
  |--tell(TaskRequest)------------>|------------->|             |           |            |
  |                 |              |              |             |           |            |
  |                 |              |  receiveMsg_TaskRequest    |           |            |
  |                 |              |<--notify_state_change()----|           |            |
  |                 |              |              |--send(TaskRequest)----->|            |
  |                 |              |              |             |           |            |
  |                 |              |         receiveMsg_TaskRequest         |            |
  |                 |              |<--notify_state_change()---|            |            |
  |                 |              |              |<--send(ResearchResult)--|            |
  |                 |              |              |             |           |            |
  |                 |         receiveMsg_ResearchResult         |           |            |
  |                 |              |<--notify_state_change()----|           |            |
  |                 |              |              |--send(ResearchResult)--------------->|
  |                 |              |              |             |           |            |
  |                 |              |              |        receiveMsg_ResearchResult     |
  |                 |              |<--notify_state_change()----|---------->|            |
  |                 |              |              |<--send(DraftContent)----|            |
  |                 |              |              |             |           |            |
  |                 |         receiveMsg_DraftContent           |           |            |
  |                 |              |<--notify_state_change()----|           |            |
  |                 |              |              |--send(ReviewRequest)---------------->|
  |                 |              |              |             |           |            |
  |                 |              |              |             |      receiveMsg_ReviewRequest
  |                 |              |              |<--send(ApprovalResponse)-------------|
  |                 |              |              |             |           |            |
  |                 |         receiveMsg_ApprovalResponse       |           |            |
  |                 |              |<--notify_state_change()----|           |            |
  |                 |              |              |             |           |            |
  |--proxy_ask(O)-->|              |              |             |           |            |
  |                 |-get_team()-->|              |             |           |            |
  |<--team----------|--------------|              |             |           |            |
  |                 |-get_messages()>|            |             |           |            |
  |<--messages------|--------------|              |             |           |            |
  |                 |-get_states()>|              |             |           |            |
  |<--states--------|--------------|              |             |           |            |
  |                 |              |              |             |           |            |
  |--shutdown()---->|              |              |             |           |            |
```

---

## Walkthrough

This example assembles all previous concepts into a realistic pipeline:

**Setup**: The Orchestrator is created first, a `SimpleLogger` is subscribed to it, then all
specialist agents are spawned via `orch_proxy.createActor(...)`. This single call auto-propagates
`team_id`, `orchestrator`, and `parent` from the orchestrator's own context into every child
agent — no manual threading of these fields is needed. Each child's startup `StartMessage` is
automatically delivered to the Orchestrator, registering it as a team member visible via
`get_team()`.

**Routing**: The `CoordinatorAgent` holds references to all other agents and acts as the
switchboard. When a message arrives it updates its own `CoordinatorState` (stage: researching /
drafting / reviewing / done) and forwards the message on. Each stage transition is a
`notify_state_change()`, giving the Orchestrator a complete audit trail.

**The pipeline** (all replies route back through the Coordinator):

```
main  →  Coordinator  →  ResearchAgent  →(ResearchResult)→  Coordinator
                      →  WriterAgent    →(DraftContent)  →  Coordinator
                      →  UserProxy      →(ApprovalResponse)→ Coordinator  → done
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

| Concept                                | Example                      |
| -------------------------------------- | ---------------------------- |
| Messages, agents, actor system         | [01](01-hello-world.md)      |
| Bidirectional messaging, proxies       | [02](02-request-response.md) |
| Dynamic spawning, parent-child         | [03](03-dynamic-agents.md)   |
| Typed state, observer, Orchestrator    | [04](04-stateful-agents.md)  |
| UserProxy, subscribers, full telemetry | 05 (this file)               |

From here you can explore `akgentic-framework` to add LLM capabilities on top of these same
patterns.
