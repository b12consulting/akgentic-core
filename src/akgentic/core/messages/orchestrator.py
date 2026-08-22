"""Orchestrator telemetry messages for actor lifecycle events.

Provides message types for tracking actor communication, state changes,
and error conditions. Used by the orchestrator for system observability.
Also home to the domain-event payloads carried by ``EventMessage.event``,
which are not ``Message`` subclasses and live beside their carrier.

The message ledger: a ``SentMessage`` **opens** the record for a message, and exactly
one of two types **closes** it — ``ProcessedMessage`` when the message had its own
turn, or ``HandledMessage`` when a run in progress absorbed it out of the mailbox and
it never got one. A consumer computing in-flight depth or per-agent queue length must
therefore close on **both**; one that closes on ``ProcessedMessage`` alone counts
absorbed mail as permanently in flight and drifts upward forever.

Source: akgentic-framework/libs/akgentic/akgentic/core/messages/orchestrator.py
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from akgentic.core.actor_address import ActorAddress
from akgentic.core.agent_config import BaseConfig
from akgentic.core.agent_state import BaseState
from akgentic.core.messages.message import Message


class SentMessage(Message):
    """Telemetry message indicating a message was sent.

    Records when an actor sends a message to another actor,
    including both the message content and the recipient. This opens the
    ledger entry for that message, closed later by either a
    ``ProcessedMessage`` or a ``HandledMessage``.

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

    Records when an actor completes processing of a message — a message that had
    its own turn. That meaning is unchanged by the arrival of ``HandledMessage``,
    and deliberately so: the two are the ledger's two terminators, and mail
    absorbed without a turn is recorded by the other one.

    Attributes:
        message_id: UUID of the processed message.
    """

    message_id: uuid.UUID


class HandledMessage(Message):
    """Telemetry message indicating a queued message was absorbed, not processed.

    Records a message that the run in progress dealt with while it sat in the
    mailbox: it was removed before delivery, so it never gets its own turn and
    no ``ReceivedMessage``/``ProcessedMessage`` pair is ever emitted for it.
    Together with ``ProcessedMessage`` it closes the ledger a ``SentMessage``
    opens — every message ends either processed or handled.

    Attributes:
        message_id: UUID of the absorbed message.
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


class NotificationMessage(Message):
    """Base telemetry message for actor-level conditions surfaced to the orchestrator.

    Attributes:
        content_type: Optional discriminator for the kind of condition — the
            raised class's name for both ErrorMessage and WarningMessage. None
            when the producer has no kind to report. Defaults so events persisted
            before this field existed stay deserializable.
        content: Human-readable text of the condition, on the base so any consumer
            reads `.content` uniformly across subclasses without an isinstance check.
            Defaults to the empty string so events persisted before this field
            existed stay deserializable.
        current_message: The message being processed when the condition occurred.
    """

    content_type: str | None = None
    content: str = ""
    current_message: Message | None = None


class ErrorMessage(NotificationMessage):
    """Telemetry message for actor errors.

    Records exceptions that occur during actor message processing. The inherited
    `content_type` carries the exception's class name and `content` its string
    form, so a generic consumer reads them without knowing the subclass.

    Attributes:
        traceback: Formatted traceback of the exception, when available.
    """

    traceback: str | None = None


class WarningMessage(NotificationMessage):
    """Telemetry message for a WarningError.

    Records a condition the actor already handled (e.g. notified a human) and is
    surfacing for observability only. Unlike ErrorMessage it carries no traceback,
    because nothing failed. It declares no fields of its own: the inherited
    `content_type` carries the raised warning's class name and `content` its text,
    the same pair an ErrorMessage uses for the exception it reports.
    """


class StateChangedMessage(Message):
    """Telemetry message for state changes.

    Records when an actor's state changes.

    Attributes:
        state: The new state after the change.
    """

    state: BaseState


class EventMessage(Message):
    """Telemetry message for actor events.

    Records domain events or custom events emitted by actors during
    their execution, allowing for event-driven monitoring and logging.

    Attributes:
        event: Domain event object emitted by a component.
    """

    event: Any


@dataclass(frozen=True)
class ClosedNotification:
    """Domain event recording that a notification was dismissed by the user.

    Carried by ``EventMessage(event=...)`` like any other domain-event
    payload — it is deliberately not a ``Message`` subclass and needs no
    orchestrator handler of its own.

    Keep it in this module: ``serialize()`` persists its import path into every
    stored event and replay resolves that string back to the class, with no
    alias mechanism — moving it breaks replay of dismissals already written.

    Attributes:
        message_id: ``id`` of the ``NotificationMessage`` that was dismissed.
    """

    message_id: uuid.UUID


@dataclass(frozen=True)
class TeamStoppingEvent:
    """Domain event recording that a team teardown has begun.

    Emitted by ``Orchestrator.stop()`` before any child is touched, so an
    out-of-process observer — a second browser tab, an operator dashboard, a
    client watching an idle-stopped session — learns that the team is going down
    instead of seeing a stopped team as a quiet running one.

    Carried by ``EventMessage(event=...)`` like any other domain-event payload —
    it is deliberately not a ``Message`` subclass and needs no orchestrator
    handler of its own. ``Message.init`` puts ``team_id``, ``timestamp`` and the
    sending orchestrator on the envelope, which is why this payload carries no
    fields of its own.

    Keep it in this module: ``serialize()`` persists its import path into every
    stored event and replay resolves that string back to the class, with no
    alias mechanism — moving it breaks replay of teardowns already written.
    """
