"""
Stateful Agents - Demonstrating State Management with Observer Pattern
=======================================================================

This example demonstrates how agents maintain and share state using BaseState
with the observer pattern and Orchestrator tracking:

- Custom state type (CounterState) with multiple fields
- State initialization with observer attachment
- Explicit state mutation with notification
- Orchestrator tracking of all state changes
- Querying final state via Orchestrator.get_states()

Run with: python examples/04_stateful_agents.py
Or with:  uv run python examples/04_stateful_agents.py
"""

from __future__ import annotations

import time

from akgentic import (
    ActorAddress,
    ActorAddressImpl,
    ActorSystemImpl,
    Akgent,
    BaseConfig,
    BaseState,
    Orchestrator,
)
from akgentic.messages import Message


# =============================================================================
# STEP 1: Define the agent state
# =============================================================================
# CounterState extends BaseState to provide observer pattern integration.
# It tracks a count, history of operations, and the last operation.
# The observer pattern allows the agent to notify the Orchestrator of changes.


class CounterState(BaseState):
    """State for a counter agent tracking count and operation history.

    Attributes:
        count: Current counter value (starts at 0).
        history: List of operation labels for audit trail.
        last_operation: Description of the most recent operation.
    """

    count: int = 0
    history: list[str] = []
    last_operation: str = ""


# =============================================================================
# STEP 2: Define message types for state mutations
# =============================================================================
# Messages tell the counter agent to perform operations that mutate state.


class IncrementMessage(Message):
    """Message to increment the counter by a specified amount.

    Attributes:
        amount: Amount to increment by (default 1).
        label: Label describing this increment operation.
    """

    amount: int = 1
    label: str = ""


class ResetMessage(Message):
    """Message to reset the counter to zero.

    Attributes:
        reason: Reason for resetting the counter.
    """

    reason: str = ""


# =============================================================================
# STEP 3: Define the counter agent with state management
# =============================================================================
# CounterAgent demonstrates:
# - Initializing state with observer attachment
# - Mutating state and notifying observers
# - Orchestrator tracking state changes


class CounterAgent(Akgent[BaseConfig, CounterState]):
    """An agent that maintains a counter with state tracking.

    This agent demonstrates:
    - BaseState subclass with multiple fields
    - Observer pattern for state change notification
    - Orchestrator tracking of all state mutations
    - Message handlers that modify state
    """

    def init(self) -> None:
        """Initialize agent with counter state and attach observer.

        Called after __init__ completes. Sets up the agent's state and
        attaches this agent as an observer to receive state change notifications.
        """
        super().init()
        # Initialize state with observer pattern
        # state.observer(self) attaches self as observer and triggers initial notification
        self.state = CounterState()
        self.state.observer(self)

    def receiveMsg_IncrementMessage(
        self, message: IncrementMessage, sender: ActorAddress | None
    ) -> None:
        """Handle increment message by updating state.

        Increments counter, records in history, and notifies observer.

        Args:
            message: IncrementMessage containing amount and label.
            sender: Address of sender (unused in this example).
        """
        # Update state fields
        self.state.count += message.amount
        self.state.history.append(message.label)
        self.state.last_operation = f"Incremented by {message.amount}"

        # Print for visibility
        print(
            f'[CounterAgent] Incremented by {message.amount} → count: {self.state.count} '
            f'(label: "{message.label}")'
        )

        # Notify observer (Orchestrator) of state change
        self.state.notify_state_change()

    def receiveMsg_ResetMessage(
        self, message: ResetMessage, sender: ActorAddress | None
    ) -> None:
        """Handle reset message by clearing counter.

        Resets counter to zero, records reason in history, and notifies observer.

        Args:
            message: ResetMessage containing reason.
            sender: Address of sender (unused in this example).
        """
        # Update state fields
        self.state.count = 0
        self.state.history.append(message.reason)
        self.state.last_operation = f"Reset ({message.reason})"

        # Print for visibility
        print(f"[CounterAgent] Reset → count: {self.state.count} (reason: \"{message.reason}\")")

        # Notify observer (Orchestrator) of state change
        self.state.notify_state_change()


# =============================================================================
# STEP 4: Main execution - create system, agents, and demonstrate state tracking
# =============================================================================


def main() -> None:
    """Run the Stateful Agents example demonstrating state management."""
    print("[Stateful Agents] Demonstrating state management with Orchestrator tracking...")

    # Create the actor system - this is the runtime that manages all agents
    actor_system = ActorSystemImpl()

    try:
        # Create an Orchestrator agent to track state changes
        orchestrator_addr = actor_system.createActor(
            Orchestrator,
            config=BaseConfig(name="orchestrator", role="Orchestrator"),
        )

        # Create the CounterAgent - need to manually pass orchestrator reference
        # because actor_system.createActor doesn't support orchestrator parameter yet
        counter_ref = CounterAgent.start(
            agent_id=None,
            config=BaseConfig(name="counter", role="Counter"),
            user_id=None,
            user_email=None,
            team_id=None,
            parent=None,
            orchestrator=orchestrator_addr,
        )
        counter_addr = ActorAddressImpl(counter_ref)

        # Send increment messages to mutate state
        actor_system.tell(
            counter_addr,
            IncrementMessage(amount=5, label="first increment"),
        )

        # Wait for async message processing
        time.sleep(0.2)

        actor_system.tell(
            counter_addr,
            IncrementMessage(amount=3, label="second increment"),
        )

        # Wait for async message processing
        time.sleep(0.2)

        actor_system.tell(
            counter_addr,
            ResetMessage(reason="starting new sequence"),
        )

        # Wait for async message processing
        time.sleep(0.2)

        actor_system.tell(
            counter_addr,
            IncrementMessage(amount=10, label="after reset"),
        )

        # Wait for async message processing
        time.sleep(0.5)

        # Query the orchestrator for tracked state
        orchestrator_proxy = actor_system.proxy_ask(orchestrator_addr, Orchestrator)

        # Get all tracked state
        states = orchestrator_proxy.get_states()

        # Count state changes by the size of history in final state
        # (each mutation adds an entry to history)
        state_change_count = 0
        if states:
            final_state = next(iter(states.values()))
            # Type guard to handle both BaseState and dict
            if isinstance(final_state, CounterState):
                state_change_count = len(final_state.history)
                print(f"[Orchestrator] Tracked {state_change_count} state changes for CounterAgent")

                # Display final state
                print(
                    f"[Orchestrator] Final state: count={final_state.count}, "
                    f"history={final_state.history}"
                )

        print("[Stateful Agents] State management demo complete.")

    finally:
        # Always clean up the actor system
        actor_system.shutdown(timeout=5)


if __name__ == "__main__":
    main()
