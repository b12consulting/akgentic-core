"""Unit tests for Orchestrator message-handler fan-out and the EventSubscriber protocol."""

import uuid
from collections.abc import Generator

import pykka
import pytest

from akgentic.core.agent_config import BaseConfig
from akgentic.core.messages.orchestrator import (
    ErrorMessage,
    ProcessedMessage,
    ReceivedMessage,
    WarningMessage,
)
from akgentic.core.orchestrator import EventSubscriber, Orchestrator


@pytest.fixture(autouse=True)
def cleanup_actors() -> Generator[None, None, None]:
    """Ensure all actors are stopped after each test."""
    yield
    pykka.ActorRegistry.stop_all()


# ---------------------------------------------------------------------------
# Orchestrator message-handler tests
# ---------------------------------------------------------------------------


class TestOrchestratorMessageHandlers:
    """Tests for the telemetry handlers' record-and-fan-out contract.

    Every handler does the same three things: skip a message the orchestrator
    sent to itself, append it to ``messages``, and forward it to every
    subscriber's ``on_message``. Messages arrive at subscribers as
    address-serialized snapshot copies, so they are compared by type and ``id``
    rather than by identity.
    """

    def _make_received_message(self) -> ReceivedMessage:
        msg_id = uuid.uuid4()
        return ReceivedMessage(message_id=msg_id)

    def _make_processed_message(self) -> ProcessedMessage:
        return ProcessedMessage(message_id=uuid.uuid4())

    def _make_error_message(self) -> ErrorMessage:
        return ErrorMessage(
            content_type="ValueError",
            content="something went wrong",
        )

    def _make_warning_message(self) -> WarningMessage:
        return WarningMessage(content="non-critical issue")

    def test_received_message_is_appended_and_fanned_out(self) -> None:
        """A ReceivedMessage from an external sender is stored and fanned out."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        subscriber = _RecordingStopSubscriber()
        orch.subscribe(subscriber).get()

        dummy_config = BaseConfig(name="dummy-agent", role="Agent")

        class _DummyOrch(Orchestrator):
            pass

        dummy_ref = _DummyOrch.start(config=dummy_config)
        sender_addr = dummy_ref.proxy().myAddress.get()

        msg = self._make_received_message()
        orch.receiveMsg_ReceivedMessage(msg, sender_addr).get()

        assert msg in orch.messages.get()
        assert [type(m) for m in subscriber.messages] == [ReceivedMessage]
        assert [m.id for m in subscriber.messages] == [msg.id]

        dummy_ref.stop()
        orch_ref.stop()

    def test_received_message_from_self_is_ignored(self) -> None:
        """A ReceivedMessage sent by the orchestrator itself is neither stored nor fanned out."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        subscriber = _RecordingStopSubscriber()
        orch.subscribe(subscriber).get()
        messages_before = len(orch.messages.get())

        my_address = orch.myAddress.get()
        orch.receiveMsg_ReceivedMessage(self._make_received_message(), my_address).get()

        assert len(orch.messages.get()) == messages_before
        assert subscriber.messages == []

        orch_ref.stop()

    def test_processed_message_is_appended_and_fanned_out(self) -> None:
        """A ProcessedMessage from an external sender is stored and fanned out."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        subscriber = _RecordingStopSubscriber()
        orch.subscribe(subscriber).get()

        dummy_config = BaseConfig(name="dummy-agent2", role="Agent")

        class _DummyOrch2(Orchestrator):
            pass

        dummy_ref = _DummyOrch2.start(config=dummy_config)
        sender_addr = dummy_ref.proxy().myAddress.get()

        msg = self._make_processed_message()
        orch.receiveMsg_ProcessedMessage(msg, sender_addr).get()

        assert msg in orch.messages.get()
        assert [type(m) for m in subscriber.messages] == [ProcessedMessage]
        assert [m.id for m in subscriber.messages] == [msg.id]

        dummy_ref.stop()
        orch_ref.stop()

    def test_processed_message_from_self_is_ignored(self) -> None:
        """A ProcessedMessage sent by the orchestrator itself is neither stored nor fanned out."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        subscriber = _RecordingStopSubscriber()
        orch.subscribe(subscriber).get()
        messages_before = len(orch.messages.get())

        my_address = orch.myAddress.get()
        orch.receiveMsg_ProcessedMessage(self._make_processed_message(), my_address).get()

        assert len(orch.messages.get()) == messages_before
        assert subscriber.messages == []

        orch_ref.stop()

    def test_warning_message_is_appended_and_fanned_out(self) -> None:
        """A WarningMessage is stored and fanned out to subscribers."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        subscriber = _RecordingStopSubscriber()
        orch.subscribe(subscriber).get()

        dummy_config = BaseConfig(name="dummy-agent5", role="Agent")

        class _DummyOrch5(Orchestrator):
            pass

        dummy_ref = _DummyOrch5.start(config=dummy_config)
        sender_addr = dummy_ref.proxy().myAddress.get()

        msg = self._make_warning_message()
        orch.receiveMsg_NotificationMessage(msg, sender_addr).get()

        assert subscriber.messages == [msg]
        assert msg in orch.messages.get()

        dummy_ref.stop()
        orch_ref.stop()

    def test_warning_message_from_self_is_ignored(self) -> None:
        """A WarningMessage sent by the orchestrator itself is neither stored nor fanned out."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        subscriber = _RecordingStopSubscriber()
        orch.subscribe(subscriber).get()
        messages_before = len(orch.messages.get())

        my_address = orch.myAddress.get()
        orch.receiveMsg_NotificationMessage(self._make_warning_message(), my_address).get()

        assert len(orch.messages.get()) == messages_before
        assert subscriber.messages == []

        orch_ref.stop()

    def test_notification_subclasses_dispatch_through_mro(self) -> None:
        """ErrorMessage and WarningMessage both reach the one consolidated handler.

        Delivered through real actor dispatch rather than a direct method call, so this
        goes red if a subclass stops resolving to receiveMsg_NotificationMessage.
        """
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        subscriber = _RecordingStopSubscriber()
        orch.subscribe(subscriber).get()

        dummy_config = BaseConfig(name="dummy-agent6", role="Agent")

        class _DummyOrch6(Orchestrator):
            pass

        dummy_ref = _DummyOrch6.start(config=dummy_config)
        sender_addr = dummy_ref.proxy().myAddress.get()

        error = self._make_error_message()
        error.init(sender_addr)
        warning = self._make_warning_message()
        warning.init(sender_addr)

        orch_ref.tell(error)
        orch_ref.tell(warning)

        # The actor drains its mailbox in order, so this proxy call is served after both tells
        stored = orch.messages.get()

        assert error in stored
        assert warning in stored

        # Subscribers get an address-serialized copy, so compare identity, not the whole model.
        # The concrete subclass must survive dispatch — it must not arrive as a bare
        # NotificationMessage.
        assert [type(m) for m in subscriber.messages] == [ErrorMessage, WarningMessage]
        assert [m.id for m in subscriber.messages] == [error.id, warning.id]

        dummy_ref.stop()
        orch_ref.stop()


class _RecordingStopSubscriber:
    """Subscriber that records on_stop / on_message invocations.

    ``on_stop_request`` is vestigial: the hook is no longer part of the
    ``EventSubscriber`` protocol and the orchestrator never dispatches it. It is
    kept here deliberately as the witness that such a subscriber still registers
    and receives the surviving hooks (structural typing). That the hook itself
    never fires is asserted by a sibling double in
    ``tests/core/test_orchestrator_no_idle_stop.py``.
    """

    def __init__(self) -> None:
        self.stop_request_count: int = 0
        self.stop_count: int = 0
        self.messages: list[object] = []

    def set_restoring(self, team_id: uuid.UUID, restoring: bool) -> None:  # noqa: FBT001
        """Protocol compliance — no-op for these tests."""
        pass

    def on_stop_request(self, team_id: uuid.UUID) -> None:
        self.stop_request_count += 1

    def on_stop(self, team_id: uuid.UUID) -> None:
        self.stop_count += 1

    def on_message(self, msg: object) -> None:
        self.messages.append(msg)


class TestEventSubscriberProtocol:
    """The ``EventSubscriber`` protocol no longer carries ``on_stop_request``."""

    def test_protocol_has_no_on_stop_request(self) -> None:
        """Idle-stop policy is a subscriber's own affair; the protocol declares no hook."""
        assert not hasattr(EventSubscriber, "on_stop_request")
