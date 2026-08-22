"""Tests for message primitives.

Tests base Message class, UserMessage, ResultMessage, and orchestrator messages.
"""

import uuid
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime

import pytest

from akgentic.core.messages.message import (
    CancelMessage,
    Message,
    ResultMessage,
    StopRecursively,
    UserMessage,
    date_time_factory,
)
from akgentic.core.messages.orchestrator import (
    ClosedNotification,
    ErrorMessage,
    EventMessage,
    HandledMessage,
    NotificationMessage,
    ProcessedMessage,
    ReceivedMessage,
    SentMessage,
    StartMessage,
    StateChangedMessage,
    StopMessage,
    TeamStoppingEvent,
    WarningMessage,
)
from akgentic.core.utils.deserializer import deserialize_object
from akgentic.core.utils.serializer import serialize


class TestDateTimeFactory:
    """Tests for date_time_factory function."""

    def test_returns_datetime(self) -> None:
        """Should return datetime object."""
        result = date_time_factory()
        assert isinstance(result, datetime)

    def test_returns_utc_timezone(self) -> None:
        """Should return datetime with UTC timezone."""
        result = date_time_factory()
        assert result.tzinfo == UTC


class TestMessage:
    """Tests for base Message class."""

    def test_auto_generates_id(self) -> None:
        """Should auto-generate UUID for id field."""
        msg = Message()
        assert isinstance(msg.id, uuid.UUID)

    def test_unique_ids(self) -> None:
        """Should generate unique IDs for each message."""
        msg1 = Message()
        msg2 = Message()
        assert msg1.id != msg2.id

    def test_auto_generates_timestamp(self) -> None:
        """Should auto-generate timestamp in UTC."""
        msg = Message()
        assert isinstance(msg.timestamp, datetime)
        assert msg.timestamp is not None
        assert msg.timestamp.tzinfo == UTC

    def test_default_display_type(self) -> None:
        """Should default display_type to 'other'."""
        msg = Message()
        assert msg.display_type == "other"

    def test_default_sender_is_none(self) -> None:
        """Should default sender to None."""
        msg = Message()
        assert msg.sender is None

    def test_default_parent_id_is_none(self) -> None:
        """Should default parent_id to None."""
        msg = Message()
        assert msg.parent_id is None

    def test_default_team_id_is_none(self) -> None:
        """Should default team_id to None."""
        msg = Message()
        assert msg.team_id is None

    def test_init_returns_self(self) -> None:
        """init() should return self for chaining."""
        msg = Message()
        result = msg.init(sender=None)
        assert result is msg

    def test_init_sets_sender(self) -> None:
        """init() should set sender."""
        msg = Message()
        sender_mock = "mock_sender"
        msg.init(sender=sender_mock)
        assert msg.sender == sender_mock

    def test_init_sets_parent_id_from_current_message(self) -> None:
        """init() should set parent_id from current_message.id."""
        parent = Message()
        child = Message()
        child.init(sender=None, current_message=parent)
        assert child.parent_id == parent.id

    def test_init_sets_team_id(self) -> None:
        """init() should set team_id."""
        msg = Message()
        team_id = uuid.uuid4()
        msg.init(sender=None, team_id=team_id)
        assert msg.team_id == team_id

    def test_init_converts_string_team_id(self) -> None:
        """init() should convert string team_id to UUID."""
        msg = Message()
        team_id = uuid.uuid4()
        msg.init(sender=None, team_id=str(team_id))  # type: ignore[arg-type]
        assert msg.team_id == team_id

    def test_explicit_id(self) -> None:
        """Should allow explicit id to be set."""
        explicit_id = uuid.uuid4()
        msg = Message(id=explicit_id)
        assert msg.id == explicit_id

    def test_serialization_includes_model_marker(self) -> None:
        """model_dump() should include __model__ marker."""
        msg = Message()
        data = msg.model_dump()
        assert "__model__" in data
        assert "akgentic.core.messages.message.Message" in data["__model__"]


class TestStopRecursively:
    """Tests for StopRecursively dataclass."""

    def test_instantiation(self) -> None:
        """Should instantiate without arguments."""
        stop = StopRecursively()
        assert stop is not None

    def test_is_dataclass(self) -> None:
        """Should be a dataclass."""
        from dataclasses import is_dataclass

        assert is_dataclass(StopRecursively)


class TestUserMessage:
    """Tests for UserMessage class."""

    def test_display_type_is_human(self) -> None:
        """Should have display_type 'human'."""
        msg = UserMessage(content="Hello")
        assert msg.display_type == "human"

    def test_content_field(self) -> None:
        """Should store content."""
        msg = UserMessage(content="Test content")
        assert msg.content == "Test content"

    def test_inherits_message_fields(self) -> None:
        """Should inherit all Message fields."""
        msg = UserMessage(content="Hello")
        assert isinstance(msg.id, uuid.UUID)
        assert isinstance(msg.timestamp, datetime)
        assert msg.sender is None

    def test_serialization(self) -> None:
        """model_dump() should include all fields."""
        msg = UserMessage(content="Hello")
        data = msg.model_dump()
        assert data["content"] == "Hello"
        assert data["display_type"] == "human"
        assert "__model__" in data


class TestResultMessage:
    """Tests for ResultMessage class."""

    def test_display_type_is_ai(self) -> None:
        """Should have display_type 'ai'."""
        msg = ResultMessage(content="Response")
        assert msg.display_type == "ai"

    def test_content_field(self) -> None:
        """Should store content."""
        msg = ResultMessage(content="AI response")
        assert msg.content == "AI response"

    def test_inherits_message_fields(self) -> None:
        """Should inherit all Message fields."""
        msg = ResultMessage(content="Response")
        assert isinstance(msg.id, uuid.UUID)
        assert isinstance(msg.timestamp, datetime)


class TestCancelMessage:
    """Tests for CancelMessage, the typed cancel carrier."""

    def test_default_reason_is_empty(self) -> None:
        """Should default reason to ''."""
        msg = CancelMessage()
        assert msg.reason == ""

    def test_default_display_type_is_other(self) -> None:
        """Should keep the inherited display_type 'other'."""
        msg = CancelMessage()
        assert msg.display_type == "other"

    def test_inherits_message_fields(self) -> None:
        """Should inherit all Message fields."""
        msg = CancelMessage()
        assert isinstance(msg.id, uuid.UUID)
        assert isinstance(msg.timestamp, datetime)
        assert msg.sender is None

    def test_init_chaining(self) -> None:
        """init() should set sender, team_id, parent_id and return self."""
        parent = Message()
        team_id = uuid.uuid4()
        msg = CancelMessage()
        result = msg.init(sender="mock_sender", team_id=team_id, current_message=parent)
        assert result is msg
        assert msg.sender == "mock_sender"
        assert msg.team_id == team_id
        assert msg.parent_id == parent.id

    def test_serialization_includes_model_marker(self) -> None:
        """model_dump() should carry the inherited __model__ marker naming CancelMessage."""
        payload = CancelMessage().model_dump()
        assert payload["__model__"] == "akgentic.core.messages.message.CancelMessage"

    def test_round_trip_preserves_class_and_reason(self) -> None:
        """A serialize/deserialize cycle restores a CancelMessage, not a plain Message."""
        msg = CancelMessage(reason="user pressed stop")

        restored = deserialize_object(serialize(msg))

        assert isinstance(restored, CancelMessage)
        assert restored.reason == "user pressed stop"
        assert restored.id == msg.id


class TestSentMessage:
    """Tests for SentMessage orchestrator message."""

    def test_instantiation(self) -> None:
        """Should instantiate with message and recipient."""
        from akgentic.core.actor_address_impl import ActorAddressProxy

        inner_msg = Message()
        recipient = ActorAddressProxy(
            {
                "name": "test",
                "role": "Worker",
                "agent_id": str(uuid.uuid4()),
            }
        )
        sent = SentMessage(message=inner_msg, recipient=recipient)
        assert sent.message is inner_msg
        assert sent.recipient == recipient

    def test_inherits_message_fields(self) -> None:
        """Should inherit all Message fields."""
        from akgentic.core.actor_address_impl import ActorAddressProxy

        inner_msg = Message()
        recipient = ActorAddressProxy(
            {
                "name": "test",
                "role": "Worker",
                "agent_id": str(uuid.uuid4()),
            }
        )
        sent = SentMessage(message=inner_msg, recipient=recipient)
        assert isinstance(sent.id, uuid.UUID)


class TestReceivedMessage:
    """Tests for ReceivedMessage orchestrator message."""

    def test_instantiation(self) -> None:
        """Should instantiate with message_id."""
        msg_id = uuid.uuid4()
        received = ReceivedMessage(message_id=msg_id)
        assert received.message_id == msg_id

    def test_does_not_have_message_field(self) -> None:
        """Should not have a message field."""
        msg_id = uuid.uuid4()
        received = ReceivedMessage(message_id=msg_id)
        assert not hasattr(received, "message")


class TestProcessedMessage:
    """Tests for ProcessedMessage orchestrator message."""

    def test_instantiation(self) -> None:
        """Should instantiate with message_id."""
        msg_id = uuid.uuid4()
        processed = ProcessedMessage(message_id=msg_id)
        assert processed.message_id == msg_id


class TestHandledMessage:
    """Tests for HandledMessage, the closing record for absorbed mail."""

    def test_instantiation(self) -> None:
        """Should instantiate with message_id."""
        msg_id = uuid.uuid4()
        handled = HandledMessage(message_id=msg_id)
        assert handled.message_id == msg_id

    def test_message_id_is_required(self) -> None:
        """Should refuse construction without a message_id."""
        with pytest.raises(ValueError):
            HandledMessage()

    def test_inherits_message_fields(self) -> None:
        """Should inherit all Message fields."""
        handled = HandledMessage(message_id=uuid.uuid4())
        assert isinstance(handled.id, uuid.UUID)
        assert isinstance(handled.timestamp, datetime)
        assert handled.sender is None

    def test_serialization_includes_model_marker(self) -> None:
        """model_dump() should carry the inherited __model__ marker naming HandledMessage."""
        payload = HandledMessage(message_id=uuid.uuid4()).model_dump()
        assert payload["__model__"] == "akgentic.core.messages.orchestrator.HandledMessage"

    def test_round_trip_preserves_class_and_message_id(self) -> None:
        """A serialize/deserialize cycle restores a HandledMessage, not a plain Message."""
        msg_id = uuid.uuid4()
        handled = HandledMessage(message_id=msg_id)

        restored = deserialize_object(serialize(handled))

        assert isinstance(restored, HandledMessage)
        assert restored.message_id == msg_id
        assert restored.id == handled.id


class TestStartMessage:
    """Tests for StartMessage orchestrator message."""

    def test_instantiation(self) -> None:
        """Should instantiate with config."""
        from akgentic.core.agent_config import BaseConfig

        config = BaseConfig(name="test", role="Worker")
        start = StartMessage(config=config)
        assert start.config == config

    def test_parent_defaults_to_none(self) -> None:
        """parent should default to None."""
        from akgentic.core.agent_config import BaseConfig

        config = BaseConfig(name="test", role="Worker")
        start = StartMessage(config=config)
        assert start.parent is None

    def test_parent_can_be_set(self) -> None:
        """parent can be explicitly set."""
        from akgentic.core.actor_address_impl import ActorAddressProxy
        from akgentic.core.agent_config import BaseConfig

        config = BaseConfig(name="test", role="Worker")
        parent = ActorAddressProxy(
            {
                "name": "parent",
                "role": "Parent",
                "agent_id": str(uuid.uuid4()),
            }
        )
        start = StartMessage(config=config, parent=parent)
        assert start.parent == parent


class TestStopMessage:
    """Tests for StopMessage orchestrator message."""

    def test_instantiation(self) -> None:
        """Should instantiate without additional fields."""
        stop = StopMessage()
        assert isinstance(stop.id, uuid.UUID)


class TestNotificationMessage:
    """Tests for NotificationMessage, the shared base of notification telemetry."""

    def test_instantiation_without_arguments(self) -> None:
        """All three fields default: content_type None, content blank, current_message None."""
        notification = NotificationMessage()
        assert notification.content_type is None
        assert notification.content == ""
        assert notification.current_message is None

    def test_content_and_current_message_can_be_set(self) -> None:
        """content and current_message are settable."""
        msg = Message()
        notification = NotificationMessage(content="x", current_message=msg)
        assert notification.content == "x"
        assert notification.current_message is msg

    def test_content_type_can_be_set(self) -> None:
        """content_type is settable on the base, not just on ErrorMessage."""
        notification = NotificationMessage(content_type="ValueError", content="boom")
        assert notification.content_type == "ValueError"

    def test_model_dump_key_set(self) -> None:
        """Serialized key set is the Message fields plus the three declared here."""
        assert set(NotificationMessage().model_dump().keys()) == {
            "id",
            "parent_id",
            "team_id",
            "timestamp",
            "sender",
            "recipient",
            "display_type",
            "content_type",
            "content",
            "current_message",
            "__model__",
        }

    def test_is_a_message(self) -> None:
        """NotificationMessage derives from Message."""
        assert isinstance(NotificationMessage(), Message)

    def test_is_not_an_error_message(self) -> None:
        """A bare NotificationMessage is not an ErrorMessage."""
        assert isinstance(NotificationMessage(content="x"), ErrorMessage) is False

    def test_model_tag_and_round_trip(self) -> None:
        """The __model__ tag names NotificationMessage; a round-trip preserves all three fields."""
        msg = Message()
        notification = NotificationMessage(content_type="Kind", content="x", current_message=msg)

        payload = notification.model_dump()
        assert payload["__model__"] == "akgentic.core.messages.orchestrator.NotificationMessage"

        restored = NotificationMessage.model_validate(payload)
        assert restored.content_type == "Kind"
        assert restored.content == "x"
        assert restored.current_message is not None
        assert restored.current_message.id == msg.id


class TestErrorMessage:
    """Tests for ErrorMessage orchestrator message."""

    def test_instantiation(self) -> None:
        """Should instantiate with the inherited content_type/content pair."""
        error = ErrorMessage(
            content_type="ValueError",
            content="Invalid input",
        )
        assert error.content_type == "ValueError"
        assert error.content == "Invalid input"

    def test_current_message_defaults_to_none(self) -> None:
        """current_message should default to None."""
        error = ErrorMessage(
            content_type="Error",
            content="msg",
        )
        assert error.current_message is None

    def test_current_message_can_be_set(self) -> None:
        """current_message can be explicitly set."""
        msg = Message()
        error = ErrorMessage(
            content_type="Error",
            content="msg",
            current_message=msg,
        )
        assert error.current_message is msg

    def test_inheritance_chain(self) -> None:
        """ErrorMessage is both a NotificationMessage and a Message."""
        error = ErrorMessage(content_type="Error", content="msg")
        assert isinstance(error, NotificationMessage)
        assert isinstance(error, Message)
        assert issubclass(ErrorMessage, NotificationMessage)
        assert issubclass(NotificationMessage, Message)

    def test_model_dump_key_set(self) -> None:
        """Serialized key set is the inherited fields plus traceback, its only own one."""
        error = ErrorMessage(content_type="E", content="v")
        assert set(error.model_dump().keys()) == {
            "id",
            "parent_id",
            "team_id",
            "timestamp",
            "sender",
            "recipient",
            "display_type",
            "content_type",
            "content",
            "current_message",
            "traceback",
            "__model__",
        }

    def test_exception_fields_are_gone(self) -> None:
        """The old exception_type/exception_value declarations no longer exist.

        The model inherits Pydantic's default extra="ignore", so passing them is
        silently dropped rather than rejected — hence the attribute check.
        """
        assert "exception_type" not in ErrorMessage.model_fields
        assert "exception_value" not in ErrorMessage.model_fields

        error = ErrorMessage(
            content_type="E",
            content="v",
            exception_type="ValueError",
            exception_value="boom",
        )
        assert hasattr(error, "exception_type") is False
        assert hasattr(error, "exception_value") is False
        with pytest.raises(AttributeError):
            _ = error.exception_value
        assert set(error.model_dump()) & {"exception_type", "exception_value"} == set()

    def test_model_tag_and_round_trip(self) -> None:
        """The __model__ tag names ErrorMessage and a dump/validate round-trip preserves fields."""
        msg = Message()
        error = ErrorMessage(
            content_type="ValueError",
            content="boom",
            traceback="tb",
            current_message=msg,
        )
        payload = error.model_dump()
        assert payload["__model__"] == "akgentic.core.messages.orchestrator.ErrorMessage"

        restored = ErrorMessage.model_validate(payload)
        assert isinstance(restored, ErrorMessage)
        assert restored.content_type == "ValueError"
        assert restored.content == "boom"
        assert restored.traceback == "tb"
        assert restored.current_message is not None
        assert restored.current_message.id == msg.id

    def test_validate_payload_without_content(self) -> None:
        """A payload persisted before the pair existed deserializes, with both at default."""
        payload = ErrorMessage(content_type="E", content="x").model_dump()
        del payload["content_type"]
        del payload["content"]

        restored = ErrorMessage.model_validate(payload)
        assert restored.content_type is None
        assert restored.content == ""

    def test_validate_payload_with_legacy_exception_keys(self) -> None:
        """An event written before the rename still replays: old keys dropped, new at default."""
        payload = ErrorMessage(content_type="E", content="x").model_dump()
        del payload["content_type"]
        del payload["content"]
        payload["exception_type"] = "ValueError"
        payload["exception_value"] = "boom"

        restored = ErrorMessage.model_validate(payload)
        assert restored.content_type is None
        assert restored.content == ""
        assert set(restored.model_dump()) & {"exception_type", "exception_value"} == set()


class TestWarningMessage:
    """Tests for WarningMessage, the telemetry a handled WarningError emits."""

    def test_instantiation_without_arguments(self) -> None:
        """Inherited fields default: content_type None, content blank, current_message None."""
        warning = WarningMessage()
        assert warning.content_type is None
        assert warning.content == ""
        assert warning.current_message is None

    def test_content_and_current_message_can_be_set(self) -> None:
        """The inherited content and current_message declarations are settable."""
        msg = Message()
        warning = WarningMessage(content="non-critical issue", current_message=msg)
        assert warning.content == "non-critical issue"
        assert warning.current_message is msg

    def test_model_dump_key_set(self) -> None:
        """Declares no fields of its own: only Message plus the three from NotificationMessage."""
        assert set(WarningMessage().model_dump().keys()) == {
            "id",
            "parent_id",
            "team_id",
            "timestamp",
            "sender",
            "recipient",
            "display_type",
            "content_type",
            "content",
            "current_message",
            "__model__",
        }

    def test_is_a_notification_and_a_message(self) -> None:
        """WarningMessage derives from NotificationMessage and therefore from Message."""
        assert issubclass(WarningMessage, NotificationMessage)
        assert issubclass(WarningMessage, Message)

    def test_is_a_sibling_of_error_message_not_a_subclass(self) -> None:
        """A WarningMessage must never satisfy an isinstance check for ErrorMessage."""
        assert issubclass(WarningMessage, ErrorMessage) is False
        assert isinstance(WarningMessage(content="x"), ErrorMessage) is False

    def test_model_tag_and_round_trip(self) -> None:
        """The __model__ tag names WarningMessage; a round-trip preserves all three fields."""
        msg = Message()
        warning = WarningMessage(content_type="WarningError", content="x", current_message=msg)

        payload = warning.model_dump()
        assert payload["__model__"] == "akgentic.core.messages.orchestrator.WarningMessage"

        restored = WarningMessage.model_validate(payload)
        assert restored.content_type == "WarningError"
        assert restored.content == "x"
        assert restored.current_message is not None
        assert restored.current_message.id == msg.id


class TestClosedNotification:
    """Tests for ClosedNotification, the payload recording a dismissed notification."""

    def test_construction_exposes_message_id(self) -> None:
        """The single field is readable back as given."""
        message_id = uuid.uuid4()
        closed = ClosedNotification(message_id=message_id)
        assert closed.message_id == message_id

    def test_is_frozen(self) -> None:
        """Reassigning the field raises, so a stored dismissal cannot be mutated in place."""
        closed = ClosedNotification(message_id=uuid.uuid4())
        with pytest.raises(FrozenInstanceError):
            closed.message_id = uuid.uuid4()  # type: ignore[misc]

    def test_is_not_a_message_subclass(self) -> None:
        """It is a payload, not telemetry: EventMessage is its carrier, not its base."""
        assert issubclass(ClosedNotification, Message) is False

    def test_serialize_emits_model_tag_and_uuid_string(self) -> None:
        """serialize() tags the class path and renders message_id as a canonical UUID string."""
        message_id = uuid.uuid4()

        payload = serialize(ClosedNotification(message_id=message_id))

        assert payload == {
            "message_id": str(message_id),
            "__model__": "akgentic.core.messages.orchestrator.ClosedNotification",
        }

    def test_deserialize_restores_message_id_as_uuid(self) -> None:
        """deserialize_object() coerces the serialized string back to a real uuid.UUID.

        The coercion depends on `uuid` staying a module-level import in
        orchestrator.py: behind TYPE_CHECKING the TypeAdapter silently fails to
        build and message_id comes back as the raw `str`, with no error raised.
        """
        message_id = uuid.uuid4()

        restored = deserialize_object(serialize(ClosedNotification(message_id=message_id)))

        assert isinstance(restored, ClosedNotification)
        assert isinstance(restored.message_id, uuid.UUID)
        assert restored.message_id == message_id

    def test_round_trip_inside_event_message(self) -> None:
        """A dump/validate cycle through the real EventMessage carrier restores the payload.

        `EventMessage.event` is typed `Any`, so `.event` must be asserted to be a
        ClosedNotification before its field is read — a plain dict would otherwise slip through.
        """
        message_id = uuid.uuid4()
        msg = EventMessage(event=ClosedNotification(message_id=message_id))

        restored = EventMessage.model_validate(msg.model_dump())

        assert isinstance(restored.event, ClosedNotification)
        assert isinstance(restored.event.message_id, uuid.UUID)
        assert restored.event.message_id == message_id


class TestTeamStoppingEvent:
    """Tests for TeamStoppingEvent, the payload announcing that a teardown has begun."""

    def test_carries_no_fields(self) -> None:
        """The envelope supplies team_id, sender and timestamp, so the payload holds nothing.

        A field added here would have to be optional forever, because events
        persisted before it must stay deserializable.
        """
        assert fields(TeamStoppingEvent()) == ()

    def test_is_frozen(self) -> None:
        """Assigning anything raises, so a stored announcement cannot be mutated in place."""
        stopping = TeamStoppingEvent()
        with pytest.raises(FrozenInstanceError):
            stopping.reason = "idle"  # type: ignore[attr-defined]

    def test_is_not_a_message_subclass(self) -> None:
        """It is a payload, not telemetry: EventMessage is its carrier, not its base.

        Being a Message would give it a receiveMsg_ handler by MRO dispatch; being
        a StopMessage in particular would make the team layer's restore logic read
        the orchestrator as one of the agents that stopped.
        """
        assert issubclass(TeamStoppingEvent, Message) is False

    def test_serialize_emits_the_model_tag_alone(self) -> None:
        """serialize() tags the class path, and with no fields that tag is the whole payload.

        The dotted path is the persisted identity: replay resolves this exact
        string back to the class and there is no alias mechanism, so relocating
        the class to another module breaks replay of events already written.
        """
        payload = serialize(TeamStoppingEvent())

        assert payload == {
            "__model__": "akgentic.core.messages.orchestrator.TeamStoppingEvent",
        }

    def test_deserialize_restores_the_class(self) -> None:
        """deserialize_object() turns the tag back into a real TeamStoppingEvent."""
        restored = deserialize_object(serialize(TeamStoppingEvent()))

        assert isinstance(restored, TeamStoppingEvent)

    def test_round_trip_inside_event_message(self) -> None:
        """A dump/validate cycle through the real EventMessage carrier restores the payload.

        `EventMessage.event` is typed `Any`, so `.event` must be asserted to be a
        TeamStoppingEvent — a plain dict would otherwise slip through.
        """
        msg = EventMessage(event=TeamStoppingEvent())

        restored = EventMessage.model_validate(msg.model_dump())

        assert isinstance(restored.event, TeamStoppingEvent)

    def test_is_importable_from_the_package_message_surface(self) -> None:
        """It is part of `akgentic.core.messages`, the surface consumers import from."""
        import akgentic.core.messages as messages

        assert messages.TeamStoppingEvent is TeamStoppingEvent
        assert "TeamStoppingEvent" in messages.__all__


class TestStateChangedMessage:
    """Tests for StateChangedMessage orchestrator message."""

    def test_instantiation(self) -> None:
        """Should instantiate with state."""
        from akgentic.core.agent_state import BaseState

        state = BaseState()
        state_changed = StateChangedMessage(state=state)
        assert state_changed.state == state
