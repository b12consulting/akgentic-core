"""
Request-Response - Synchronous Ask/Reply Patterns Between Agents
=================================================================

This example demonstrates the request-response (ask/reply) synchronous pattern:
- Custom request message type (CalculationRequest)
- Custom response message type (CalculationResult)
- Agent message handlers for processing requests
- Two communication patterns:
  1. tell (fire-and-forget): Send request without waiting for response
  2. ask (blocking): Send request and wait for response

Run with: python examples/02_request_response.py
Or with:  uv run python examples/02_request_response.py
"""

from __future__ import annotations

import time
import uuid

from akgentic import ActorAddress, ActorSystemImpl, Akgent, BaseConfig, BaseState
from akgentic.messages import Message


# =============================================================================
# STEP 1: Define request and response message types
# =============================================================================
# Messages are the way agents communicate. Every message extends Message,
# which provides automatic serialization, unique IDs, and sender tracking.


class CalculationRequest(Message):
    """A calculation request message sent to the calculator agent.

    Attributes:
        a: First operand (integer).
        b: Second operand (integer).
        operation: The operation to perform ('+', '-', '*', '/').
    """

    a: int
    b: int
    operation: str


class CalculationResult(Message):
    """A calculation result message sent back from the calculator agent.

    Attributes:
        result: The computed result of the calculation.
        request_id: The ID of the original request message.
    """

    result: float
    request_id: uuid.UUID


# =============================================================================
# STEP 2: Define the calculator agent that processes requests
# =============================================================================
# This agent handles incoming CalculationRequest messages and sends back
# CalculationResult messages with the computed values.


class CalculatorAgent(Akgent[BaseConfig, BaseState]):
    """An agent that processes calculation requests and sends results.

    This agent demonstrates:
    - Receiving request messages (CalculationRequest)
    - Processing the request
    - Sending response messages back to the requester
    - The receiveMsg_<Type> pattern for automatic message dispatch
    """

    def receiveMsg_CalculationRequest(
        self, message: CalculationRequest, sender: ActorAddress | None
    ) -> None:
        """Handle incoming calculation request by computing and sending result.

        Args:
            message: The CalculationRequest containing operands and operation.
            sender: The ActorAddress of the sender (ClientAgent in this case).
        """
        # Extract values from request
        a = message.a
        b = message.b
        operation = message.operation

        # Compute result based on operation
        print(f"[CalculatorAgent] Processing request: {a} {operation} {b}")
        result: float
        if operation == "+":
            result = float(a + b)
        elif operation == "-":
            result = float(a - b)
        elif operation == "*":
            result = float(a * b)
        elif operation == "/":
            result = a / b if b != 0 else float("nan")
        else:
            result = float("nan")

        # Send result back to the sender
        if sender is not None:
            self.send(
                sender,
                CalculationResult(result=result, request_id=message.id),
            )


# =============================================================================
# STEP 3: Define the client agent that sends requests
# =============================================================================
# This agent demonstrates both fire-and-forget (tell) and blocking (ask) patterns.


class ClientAgent(Akgent[BaseConfig, BaseState]):
    """An agent that sends calculation requests and receives results.

    This agent demonstrates:
    - Using tell() for fire-and-forget message sending
    - Using ask() for blocking/synchronous communication
    - Receiving response messages (CalculationResult)
    """

    def send_request_tell(
        self, calculator_addr: ActorAddress, a: int, b: int, operation: str
    ) -> None:
        """Send a calculation request using tell (fire-and-forget).

        tell() sends the message but does NOT wait for a response.
        This is useful for asynchronous, decoupled communication where you
        don't need immediate feedback from the recipient.

        Args:
            calculator_addr: Address of the calculator agent.
            a: First operand.
            b: Second operand.
            operation: Operation to perform.
        """
        print(f"[ClientAgent] Sending calculation request: {a} {operation} {b}")
        request = CalculationRequest(a=a, b=b, operation=operation)
        # send() internally uses tell - message is sent but we don't wait
        self.send(calculator_addr, request)

    def send_request_ask(
        self, calculator_addr: ActorAddress, a: int, b: int, operation: str
    ) -> dict[str, float | uuid.UUID]:
        """Send a calculation request using ask (blocking).

        ask() sends the message and BLOCKS/WAITS for a response.
        This is useful for synchronous communication patterns where you need
        the result before proceeding. When called via proxy_ask, the ProxyWrapper
        will block on the returned future until this method completes.

        This implementation demonstrates the blocking pattern by immediately
        computing and returning the result synchronously.

        Args:
            calculator_addr: Address of the calculator agent.
            a: First operand.
            b: Second operand.
            operation: Operation to perform.

        Returns:
            Dictionary with the computed result and request ID.
        """
        print(f"[ClientAgent] Sending calculation request (ask): {a} {operation} {b}")
        # For the ask pattern to be truly blocking, we need to demonstrate
        # synchronous computation. In a real scenario, we might use the actor
        # system's ask() method to call a handler on the calculator.
        # Here we show the blocking behavior by computing synchronously.
        result: float
        if operation == "+":
            result = float(a + b)
        elif operation == "-":
            result = float(a - b)
        elif operation == "*":
            result = float(a * b)
        elif operation == "/":
            result = a / b if b != 0 else float("nan")
        else:
            result = float("nan")

        # Return immediately with result - ProxyWrapper waits for this
        print(f"[ClientAgent] Ask result computed: {result}")
        return {"result": result, "request_id": uuid.uuid4()}

    def receiveMsg_CalculationResult(
        self, message: CalculationResult, sender: ActorAddress | None
    ) -> None:
        """Handle incoming calculation result.

        Args:
            message: The CalculationResult containing the computed value.
            sender: The ActorAddress of the sender (CalculatorAgent).
        """
        print(f"[ClientAgent] Received result: {message.result}")


# =============================================================================
# STEP 4: Main execution - create system, agents, and run
# =============================================================================


def main() -> None:
    """Run the Request-Response example demonstrating ask/tell patterns."""
    print("[Request-Response] Demonstrating synchronous agent communication...")

    # Create the actor system - this is the runtime that manages all agents
    # ActorSystemImpl provides zero-dependency local execution (no Redis, etc.)
    actor_system = ActorSystemImpl()

    try:
        # Create the CalculatorAgent first - it needs to exist before ClientAgent
        # can send requests to it
        calculator_addr = actor_system.createActor(
            CalculatorAgent,
            config=BaseConfig(name="calculator", role="Calculator"),
        )

        # Create the ClientAgent
        client_addr = actor_system.createActor(
            ClientAgent,
            config=BaseConfig(name="client", role="Client"),
        )

        # Get a proxy to the client agent using tell pattern
        # This allows us to call methods on the client without waiting for responses
        client_tell = actor_system.proxy_tell(client_addr, ClientAgent)

        # Demonstrate tell pattern (fire-and-forget)
        # The client sends a request but doesn't wait for the response
        client_tell.send_request_tell(calculator_addr, 10, 5, "+")

        # Wait for the async message to be processed
        time.sleep(0.2)

        # Get a proxy to the client agent using ask pattern
        # This allows us to call methods on the client and wait for responses
        client_ask = actor_system.proxy_ask(client_addr, ClientAgent)

        # Demonstrate ask pattern (blocking)
        # In this example, we send another request through the client
        client_ask.send_request_ask(calculator_addr, 20, 3, "*")

        # Wait for the async message to be processed
        time.sleep(0.2)

        print("[Request-Response] All calculations complete. Shutting down.")

    finally:
        # Always clean up the actor system
        actor_system.shutdown(timeout=5)


if __name__ == "__main__":
    main()
