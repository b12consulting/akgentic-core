"""Orchestrator telemetry messages for actor lifecycle events.

Provides message types for tracking actor communication, state changes,
and error conditions. Used by the orchestrator for system observability.

Source: akgentic-framework/libs/akgentic/akgentic/core/messages/orchestrator.py
"""

from __future__ import annotations

import uuid
from typing import Any

from akgentic.actor_address import ActorAddress
from akgentic.agent_config import BaseConfig
from akgentic.agent_state import BaseState
from akgentic.messages.message import Message


class SentMessage(Message):
    """Telemetry message indicating a message was sent.

    Records when an actor sends a message to another actor,
    including both the message content and the recipient.

    Attributes:
        message: The message that was sent.
        recipient: Address of the receiving actor.
    """

    message: Message
    recipient: ActorAddress


class ReceivedMessage(Message):
    """Telemetry message indicating a message was received.

    Records when an actor receives a message from another actor,
    storing only the message ID for lightweight telemetry.

    Attributes:
        message_id: UUID of the received message.
    """

    message_id: uuid.UUID


class ProcessedMessage(Message):
    """Telemetry message indicating a message was processed.

    Records when an actor completes processing of a message.

    Attributes:
        message_id: UUID of the processed message.
    """

    message_id: uuid.UUID


class StartMessage(Message):
    """Message to start an actor with configuration.

    Signals that an actor should initialize with the provided
    configuration and optional parent reference.

    Attributes:
        config: Actor configuration for initialization.
        parent: Optional parent actor address.
    """

    config: BaseConfig
    parent: ActorAddress | None = None


class StopMessage(Message):
    """Message to stop an actor.

    Signals that the receiving actor should stop processing
    and clean up resources.
    """

    pass


class ErrorMessage(Message):
    """Telemetry message for actor errors.

    Records exceptions that occur during actor message processing,
    including the error details and the message being processed.

    Attributes:
        exception_type: Fully qualified name of the exception class.
        exception_value: String representation of the exception.
        current_message: The message being processed when error occurred.
    """

    exception_type: str
    exception_value: str
    current_message: Message | None = None


class ContextChangedMessage(Message):
    """Telemetry message for context changes.

    Records when an actor's conversation context changes,
    typically due to new messages being added.

    Attributes:
        messages: List of messages in the updated context.
        err: Optional exception if context change failed.
    """

    messages: list[Any]
    err: BaseException | None = None


class StateChangedMessage(Message):
    """Telemetry message for state changes.

    Records when an actor's state changes, including the
    new state and any errors during the transition.

    Attributes:
        state: The new state after the change.
        err: Optional exception if state change failed.
    """

    state: BaseState
    err: BaseException | None = None


class ToolUpdateMessage(Message):
    """Telemetry message for tool execution updates.

    Records updates from tool executions, including the tool
    name, returned data, and optional metadata.

    Attributes:
        tool: Name of the tool that generated the update.
        data: Data returned by the tool.
        metadata: Optional additional metadata about the execution.
    """

    tool: str
    data: Any
    metadata: dict[str, Any] | None = None
