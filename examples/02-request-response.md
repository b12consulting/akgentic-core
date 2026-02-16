# 02 — Request-Response

> A client agent sends a calculation request and receives the result back, introducing
> bidirectional messaging and the `ask` / `tell` distinction.

---

## Concepts introduced

### Replying to a message

In [example 01](01-hello-world.md), messages only flowed in one direction. Here, the
`CalculatorAgent` sends a response *back* to the caller. The `sender` parameter of every
handler gives you the address to reply to:

```python
def receiveMsg_CalculationRequest(self, message: CalculationRequest, sender: ActorAddress | None) -> None:
    result = compute(message)
    if sender is not None:
        self.send(sender, CalculationResult(result=result, request_id=message.id))
```

`message.id` is the built-in UUID every `Message` carries — useful for correlating a response
back to its original request.

---

### tell vs ask

When calling agent methods from outside the actor system, you have two modes:

| Mode | Method | Behaviour |
|---|---|---|
| **fire-and-forget** | `proxy_tell()` | Returns immediately; you don't get the result |
| **blocking** | `proxy_ask()` | Blocks the caller until the agent method returns |

Both modes require a **proxy**: a thin wrapper that lets you call agent methods as if they were
regular Python functions, while the actual execution happens inside the agent's mailbox.

```python
# Fire-and-forget: call the method, don't wait
client_tell = actor_system.proxy_tell(client_addr, ClientAgent)
client_tell.send_request_tell(calculator_addr, 10, 5, "+")

# Blocking: call the method and wait for the return value
client_ask = actor_system.proxy_ask(client_addr, ClientAgent)
result = client_ask.send_request_ask(calculator_addr, 20, 3, "*")
```

Use `tell` when you don't need the result. Use `ask` when you need to wait for it before
continuing.

---

### Request / response message pairing

A common pattern is to define a matching pair of messages:

```python
class CalculationRequest(Message):
    a: int
    b: int
    operation: str

class CalculationResult(Message):
    result: float
    request_id: uuid.UUID   # ties back to the original request
```

The `request_id` field stores the `id` of the original `CalculationRequest`, so the caller can
match each response to the request that triggered it. This is essential in systems where
multiple requests may be in-flight simultaneously.

---

## Message flow

```
main()               ActorSystem          ClientAgent          CalculatorAgent
  |                      |                    |                      |
  |--createActor(Calc)-->|                    |                      |
  |                      |--spawn-------------|--------------------->|
  |                      |                    |                      |
  |--createActor(Cli)--->|                    |                      |
  |                      |--spawn------------>|                      |
  |                      |                    |                      |
  |                                                                   |
  |  [ tell pattern — fire and forget ]                               |
  |                      |                    |                      |
  |--proxy_tell()------->|                    |                      |
  |                      |--send_request_tell>|                      |
  |                      |                    |--send(CalcRequest)-->|
  |                      |                    |                      |
  |                      |                    |   receiveMsg_CalculationRequest
  |                      |                    |<--send(CalcResult)---|
  |                      |                    |                      |
  |                      |  receiveMsg_CalculationResult             |
  |                      |                    |                      |
  |                                                                   |
  |  [ ask pattern — blocking ]                                       |
  |                      |                    |                      |
  |--proxy_ask()-------->|                    |                      |
  |                      |--send_request_ask->|                      |
  |<-----result returned immediately (synchronous computation)--------|
  |                      |                    |                      |
  |--shutdown()--------->|                    |                      |
```

---

## Walkthrough

The key insight of this example is the two **communication modes** exposed by the proxy:

**`proxy_tell`** wraps agent method calls in fire-and-forget mode. The main thread sends the
command and moves on immediately. Any response will arrive later via `receiveMsg_CalculationResult`.

**`proxy_ask`** wraps agent method calls in blocking mode. The main thread waits until the
agent method returns. This is useful when you need the result before doing anything else.

The `CalculatorAgent` always uses `self.send(sender, result)` — it doesn't need to know which
mode the caller used. The proxy layer handles the difference transparently.

---

## Running it

```bash
uv run python examples/02_request_response.py
```

Expected output:

```
[Request-Response] Demonstrating synchronous agent communication...
[ClientAgent] Sending calculation request: 10 + 5
[ClientAgent] Received result: 15.0
[ClientAgent] Sending calculation request (ask): 20 * 3
[ClientAgent] Ask result computed: 60.0
[Request-Response] All calculations complete. Shutting down.
```

---

## What's next

→ [03 — Dynamic Agents](03-dynamic-agents.md): agents that spawn other agents at runtime.
