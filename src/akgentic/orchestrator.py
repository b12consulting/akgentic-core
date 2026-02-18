"""Orchestrator agent for workflow coordination and telemetry tracking.

This module provides an Orchestrator agent that manages workflow coordination
and telemetry without external dependencies. It tracks agent lifecycle events,
message flows, and state changes using in-memory storage.
"""

import logging
import os
import threading
from collections.abc import Callable
from typing import Any, Protocol, overload, override

from akgentic.actor_address import ActorAddress
from akgentic.agent import Akgent
from akgentic.agent_config import BaseConfig
from akgentic.agent_state import BaseState
from akgentic.messages.message import Message, StopRecursively
from akgentic.messages.orchestrator import (
    ContextChangedMessage,
    ErrorMessage,
    ProcessedMessage,
    ReceivedMessage,
    SentMessage,
    StartMessage,
    StateChangedMessage,
    StopMessage,
    ToolUpdateMessage,
)

logger = logging.getLogger(__name__)

TIMER_DELAY = 3600  # 1 hour default inactivity timeout


class Timer:
    """Helper class for inactivity timeout management.

    Tracks active tasks and triggers a timeout callback after a configurable
    delay when the orchestrator becomes idle (task_count reaches 0).

    The timer automatically cancels itself when tasks are active and restarts
    when the orchestrator becomes idle again.

    Args:
        delay: Seconds of inactivity before timeout_callback is invoked.
        timeout_callback: Zero-argument callable invoked on timeout.

    Example:
        >>> def on_timeout():
        ...     print("Timed out!")
        >>> timer = Timer(delay=60, timeout_callback=on_timeout)
        >>> timer.start()
        >>> timer.task_started()   # pauses countdown
        >>> timer.task_completed() # restarts countdown
        >>> timer.cancel()         # prevents callback from firing
    """

    def __init__(self, delay: int, timeout_callback: Callable[[], None]) -> None:
        self.delay = delay
        self.timeout_callback = timeout_callback
        self.task_count: int = 0
        self._timer: threading.Timer | None = None

    def start(self) -> None:
        """Start or restart the countdown timer.

        Cancels any existing timer before starting a new one.
        """
        self.cancel()
        self._timer = threading.Timer(self.delay, self.timeout_callback)
        self._timer.daemon = True
        self._timer.start()

    def cancel(self) -> None:
        """Cancel the current timer, preventing the callback from firing."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def task_started(self) -> None:
        """Increment task count and cancel timer while tasks are active."""
        self.task_count += 1
        if self.task_count > 0:
            self.cancel()

    def task_completed(self) -> None:
        """Decrement task count and restart timer when orchestrator becomes idle."""
        self.task_count -= 1
        if self.task_count <= 0:
            self.task_count = 0  # Prevent negative count
            self.start()


class OrchestratorEventSubscriber(Protocol):
    """Protocol for subscribing to orchestrator events.

    Implementations can provide custom handling for workflow events such as
    Redis publishing, WebSocket streaming, or database persistence.

    Phase 3 implementations:
        - RedisEventSubscriber: Publishes events to Redis streams
        - WebSocketEventSubscriber: Streams events to WebSocket clients
        - PostgresEventSubscriber: Persists events to PostgreSQL
    """

    def on_stop(self) -> None:
        """Called when an orchestrator stops."""
        ...

    def on_message(self, msg: Message) -> None:
        """Called when an agent life-cycle message is received:
            - StartMessage
            - StopMessage
            - SentMessage
            - ReceivedMessage
            - ProcessedMessage
            - ErrorMessage

        Args:
            msg: Orchestrator telemetry message
        """
        ...

    def on_state_changed(self, msg: StateChangedMessage) -> None:
        """Called when an agent's state changes.

        Args:
            msg: StateChangedMessage containing updated state
        """
        ...

    def on_llm_context_changed(self, msg: ContextChangedMessage) -> None:
        """Called when an agent's LLM context changes.

        Args:
            msg: ContextChangedMessage containing updated LLM context
        """
        ...

    def on_tool_update(self, msg: ToolUpdateMessage) -> None:
        """Called when a tool's state is updated.

        Args:
            msg: ToolUpdateMessage containing tool state update
        """
        ...


class Orchestrator(Akgent[BaseConfig, BaseState]):
    """Orchestrator agent for workflow coordination and telemetry tracking.

    The Orchestrator manages workflow coordination and telemetry tracking without
    external dependencies. It maintains in-memory storage of:
        - Message history (all telemetry events)
        - Per-agent state snapshots
        - Per-agent LLM context
        - Per-tool state tracking
        - Team roster (computed from message history)

    The Orchestrator uses a subscriber pattern to enable extensibility. Subscribers
    can implement custom event handling for features like Redis publishing, WebSocket
    streaming, or database persistence.

    Attributes:
        messages: Complete message history (all telemetry events)
        state_dict: Per-agent state snapshots (keyed by agent_id string)
        llm_context_dict: Per-agent LLM context (keyed by agent_id string)
        tool_state_dict: Per-tool state tracking
        subscribers: List of event subscribers for extensibility

    Example:
        >>> system = ActorSystem.start().proxy()
        >>> orchestrator_ref = system.create_agent(
        ...     Orchestrator,
        ...     config=BaseConfig(name="orchestrator", role="Orchestrator")
        ... )
        >>> # Agents automatically send telemetry to orchestrator
        >>> messages = orchestrator_ref.get_messages().get()
    """

    @override
    def init(self) -> None:
        """Initialize the Orchestrator with empty in-memory state.

        The inactivity timer delay is configurable via the
        ``ORCHESTRATOR_TIMEOUT_DELAY`` environment variable (seconds).
        Defaults to 3600 seconds (1 hour) when the variable is not set.

        Args:
            config: Base configuration for the agent
            **kwargs: Additional keyword arguments passed to parent Akgent class
        """
        self._orchestrator = self.myAddress

        # Message history
        self.messages: list[Message] = []

        # Per-agent state tracking
        self.state_dict: dict[str, BaseState | dict[str, Any]] = {}
        self.llm_context_dict: dict[str, list[Any]] = {}
        self.tool_state_dict: dict[str, dict[str, Any]] = {}

        # Team roster cache
        self._current_team_members: list[ActorAddress] | None = None

        # Shutdown flag
        self._stopping: bool = False

        # Event subscribers for Phase 3 extensibility
        self.subscribers: list[OrchestratorEventSubscriber] = []

        # Inactivity timer — configurable via env var, defaults to TIMER_DELAY
        timer_delay = int(os.environ.get("ORCHESTRATOR_TIMEOUT_DELAY", str(TIMER_DELAY)))
        self._timer = Timer(delay=timer_delay, timeout_callback=self._timeout_handler)
        self._timer.start()

        # Notify orchestrator of its own startup
        start_message = StartMessage(config=self.config)
        start_message.init(self.myAddress, self._team_id)
        self.receiveMsg_StartMessage(start_message, self.myAddress)

    @override
    def on_stop(self) -> None:
        self._notify_subscribers("on_stop")
        super().on_stop()
        logger.info(f">>> [{self.config.name}] Stopped !")

    @override
    def _notify_orchestrator(self, message: Message) -> None:
        """Override to directly append orchestrator's own messages without telemetry cascade."""
        pass

    def _timeout_handler(self) -> None:
        """Handle inactivity timeout by stopping the orchestrator.

        Logs the timeout event with the team ID from config, then sends
        a ``StopRecursively`` message to self to trigger graceful shutdown.
        Any exception during the stop is caught and logged to prevent the
        timer thread from crashing silently.
        """
        team_id = getattr(self.config, "team_id", "unknown")
        logger.info(f"Orchestrator timeout after {self._timer.delay}s inactivity (team={team_id})")
        self.send(self.myAddress, StopRecursively())

    def get_timer(self) -> Timer:
        """Return the inactivity Timer instance (for testing and introspection).

        Returns:
            The Timer managing inactivity-based shutdown.
        """
        return self._timer

    def subscribe(self, subscriber: OrchestratorEventSubscriber) -> None:
        """Add an event subscriber to receive orchestrator events.

        Args:
            subscriber: Subscriber implementing OrchestratorEventSubscriber protocol
        """
        self.subscribers.append(subscriber)

    def _notify_subscribers(self, event_method: str, message: Message | None = None) -> None:
        """Unified subscriber notification with fault tolerance.

        Args:
            event_method: Name of the subscriber method to call
            message: Message to pass to subscriber
        """
        for subscriber in self.subscribers:
            try:
                method = getattr(subscriber, event_method)
                if message is None:
                    method()
                else:
                    method(message)
            except Exception as e:
                logger.error(
                    f"Subscriber {subscriber.__class__.__name__} failed {event_method}: {e}"
                )

    def receiveMsg_StartMessage(self, message: StartMessage, sender: ActorAddress) -> None:
        """Handle agent start events.

        Args:
            message: StartMessage from agent
            sender: ActorAddress of sending agent
        """
        self.messages.append(message)
        self._current_team_members = None  # Clear cache
        self._notify_subscribers("on_message", message)

    def receiveMsg_StopMessage(self, message: StopMessage, sender: ActorAddress) -> None:
        """Handle agent stop events.

        Skips recording if orchestrator is shutting down (_stopping flag).

        Args:
            message: StopMessage from agent
            sender: ActorAddress of sending agent
        """
        if self._stopping:
            # Don't record StopMessages during orchestrator shutdown
            return

        self.messages.append(message)
        self._current_team_members = None  # Clear cache
        self._notify_subscribers("on_message", message)

    def receiveMsg_SentMessage(self, message: SentMessage, sender: ActorAddress) -> None:
        """Handle message sent events.

        Args:
            message: SentMessage containing sent message details
            sender: ActorAddress of sending agent
        """
        # Skip orchestrator's own telemetry to avoid recursion
        if sender == self.myAddress:
            return
        self.messages.append(message)
        self._notify_subscribers("on_message", message)

    def receiveMsg_ReceivedMessage(self, message: ReceivedMessage, sender: ActorAddress) -> None:
        """Handle message received events.

        Args:
            message: ReceivedMessage containing received message details
            sender: ActorAddress of sending agent
        """
        # Skip orchestrator's own telemetry to avoid recursion
        if sender == self.myAddress:
            return
        self._timer.task_started()
        self.messages.append(message)
        self._notify_subscribers("on_message", message)

    def receiveMsg_ProcessedMessage(self, message: ProcessedMessage, sender: ActorAddress) -> None:
        """Handle message processed events.

        Args:
            message: ProcessedMessage containing processing completion details
            sender: ActorAddress of sending agent
        """
        # Skip orchestrator's own telemetry to avoid recursion
        if sender == self.myAddress:
            return
        self._timer.task_completed()
        self.messages.append(message)
        self._notify_subscribers("on_message", message)

    def receiveMsg_ErrorMessage(self, message: ErrorMessage, sender: ActorAddress) -> None:
        """Handle error events (treat as task completion for timer purposes).

        Args:
            message: ErrorMessage containing error details
            sender: ActorAddress of sending agent
        """
        # Skip orchestrator's own telemetry to avoid recursion
        if sender == self.myAddress:
            return
        self._timer.task_completed()
        self.messages.append(message)
        self._notify_subscribers("on_message", message)

    def receiveMsg_StateChangedMessage(
        self, message: StateChangedMessage, sender: ActorAddress
    ) -> None:
        """Handle agent state change events.

        Args:
            message: StateChangedMessage containing updated state
            sender: ActorAddress of sending agent
        """
        self.state_dict[str(sender.agent_id)] = message.state
        self._notify_subscribers("on_state_changed", message)

    def receiveMsg_ContextChangedMessage(
        self, message: ContextChangedMessage, sender: ActorAddress
    ) -> None:
        """Handle LLM context change events.

        Args:
            message: ContextChangedMessage containing updated LLM context
            sender: ActorAddress of sending agent
        """
        self.llm_context_dict[str(sender.agent_id)] = message.messages
        self._notify_subscribers("on_llm_context_changed", message)

    def receiveMsg_ToolUpdateMessage(
        self, message: ToolUpdateMessage, sender: ActorAddress
    ) -> None:
        """Handle tool state update events.

        Args:
            message: ToolUpdateMessage containing tool state update
            sender: ActorAddress of sending agent
        """
        timestamp = message.timestamp.isoformat() if message.timestamp else None
        self.tool_state_dict[message.tool] = {
            "data": message.data,
            "timestamp": timestamp,
        }
        self._notify_subscribers("on_tool_update", message)

    def get_team(self) -> list[ActorAddress]:
        """Get list of active agents (excludes Orchestrator role).

        Team is computed from message history: agents that sent StartMessage
        but not StopMessage. Result is cached and cleared when team membership changes.

        Returns:
            List of ActorAddress for active team members
        """
        if self._current_team_members is not None:
            return self._current_team_members

        # Compute from message history using comprehensions
        started_agentid_addr_dict = {
            str(msg.sender.agent_id): msg.sender
            for msg in self.messages
            if isinstance(msg, StartMessage)
            and msg.sender is not None
            and msg.sender.role != "Orchestrator"
        }
        stopped_agent_id_set = {
            str(msg.sender.agent_id)
            for msg in self.messages
            if isinstance(msg, StopMessage) and msg.sender is not None
        }

        # Active = started but not stopped
        active = [
            addr
            for aid, addr in started_agentid_addr_dict.items()
            if aid not in stopped_agent_id_set
        ]

        # Cache result
        self._current_team_members = active
        return active

    def get_team_member(self, member: str) -> ActorAddress | None:
        """Get a team member by name or agent_id.

        Args:
            member: Agent name or agent_id (as string or UUID)

        Returns:
            ActorAddress if found, None otherwise
        """
        return next(
            (
                mbr
                for mbr in self.get_team()
                if mbr.name == str(member) or str(mbr.agent_id) == str(member)
            ),
            None,
        )

    @overload
    def get_messages(self) -> list[Message]: ...

    @overload
    def get_messages(self, sender: ActorAddress) -> tuple[list[Message], list[Message]]: ...

    def get_messages(
        self, sender: ActorAddress | None = None
    ) -> list[Message] | tuple[list[Message], list[Message]]:
        """Get messages from message history.

        Args:
            sender: Optional ActorAddress to filter messages by sender.
                   If provided, returns tuple of (requests, answers).
                   If None, returns all messages.

        Returns:
            If sender is None: list of all messages
            If sender provided: tuple of (requests from sender, answers to sender)
        """
        if sender:
            # Filter for HelpRequestMessage from sender
            requests = [
                request.message
                for request in self.messages
                if request.sender == sender
                and isinstance(request, SentMessage)
                and request.message.__class__.__name__ == "HelpRequestMessage"
            ]
            request_ids = {req.id for req in requests}

            # Filter for HelpAnswerMessage matching requests
            answers = [
                answer.message
                for answer in self.messages
                if isinstance(answer, SentMessage)
                and answer.message.__class__.__name__ == "HelpAnswerMessage"
                and hasattr(answer.message, "request_id")
                and answer.message.request_id in request_ids  # type: ignore
            ]
            return requests, answers

        return self.messages

    def get_llm_context(self) -> dict[str, list[Any]]:
        """Get all LLM contexts tracked by orchestrator.

        Returns:
            Dictionary mapping agent_id (as string) to LLM message list
        """
        return self.llm_context_dict

    def get_states(self) -> dict[str, BaseState | dict[str, Any]]:
        """Get all agent states tracked by orchestrator.

        Returns:
            Dictionary mapping agent_id (as string) to agent state
        """
        return self.state_dict

    def get_tool_state(self, tool: str | None = None) -> dict[str, Any]:
        """Get tool state for specific tool or all tools.

        Args:
            tool: Tool name to get state for. If None, returns all tool states.

        Returns:
            If tool is None: dictionary of all tool states
            If tool provided: dictionary with tool state (or empty dict if not found)
        """
        if tool:
            return self.tool_state_dict.get(tool, {})
        return self.tool_state_dict

    def stop(self) -> None:
        """Override stop to cancel timer and set _stopping flag before shutdown.

        Cancels the inactivity timer first to prevent it from firing during
        shutdown, then sets the _stopping flag to suppress StopMessage recording,
        then calls the parent stop() method.
        """
        self._timer.cancel()
        self._stopping = True
        super().stop()
