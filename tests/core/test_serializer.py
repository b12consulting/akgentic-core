"""Tests for serialization utilities.

Tests serialize functions, SerializableBaseModel, and deserialize_object.
"""

import base64
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pydantic.dataclasses
import pytest
from pydantic import BaseModel

from akgentic.core.messages.message import Message, UserMessage
from akgentic.core.utils.deserializer import (
    ActorAddressDict,
    DeserializeContext,
    deserialize_object,
    import_class,
    is_uuid_canonical,
)
from akgentic.core.utils.serializer import (
    SerializableBaseModel,
    get_field_serializers_map,
    serialize,
    serialize_base_model,
    serialize_type,
)


# Module-level test fixtures for pydantic dataclass tests.
# These must be at module level so serialize_type/import_class can find them.
@pydantic.dataclasses.dataclass
class FakeBinaryContent:
    """Test fixture mimicking pydantic-ai's BinaryContent."""

    data: bytes
    media_type: str


@pydantic.dataclasses.dataclass
class FakeMultimodalPart:
    """Pydantic dataclass with nested bytes for realistic round-trip testing."""

    content: bytes
    mime_type: str
    label: str


@dataclass
class PlainEvent:
    """Plain stdlib dataclass for regression testing."""

    name: str
    count: int


@dataclass
class PlainEventWithBinary:
    """Plain dataclass containing a pydantic dataclass with bytes (realistic nesting)."""

    event_name: str
    payload: FakeBinaryContent


class TestSerializeType:
    """Tests for serialize_type function."""

    def test_serializes_class(self) -> None:
        """Should serialize class to module.ClassName."""
        result = serialize_type(Message)
        assert result == "akgentic.core.messages.message.Message"

    def test_serializes_instance(self) -> None:
        """Should serialize instance to module.ClassName."""
        msg = Message()
        result = serialize_type(msg)
        assert result == "akgentic.core.messages.message.Message"

    def test_serializes_builtin_type(self) -> None:
        """Should serialize builtin types."""
        result = serialize_type(str)
        assert result == "builtins.str"


class TestSerialize:
    """Tests for serialize function."""

    def test_serialize_none(self) -> None:
        """Should return None for None."""
        assert serialize(None) is None

    def test_serialize_uuid(self) -> None:
        """Should serialize UUID to string."""
        uid = uuid.uuid4()
        result = serialize(uid)
        assert result == str(uid)

    def test_serialize_datetime(self) -> None:
        """Should serialize datetime to ISO format."""
        dt = datetime.now(UTC)
        result = serialize(dt)
        assert result == dt.isoformat()

    def test_serialize_type(self) -> None:
        """Should serialize type to dict with __type__."""
        result = serialize(str)
        assert result == {"__type__": "builtins.str"}

    def test_serialize_list(self) -> None:
        """Should serialize list recursively."""
        uid = uuid.uuid4()
        result = serialize([uid, None, "test"])
        assert result == [str(uid), None, "test"]

    def test_serialize_set(self) -> None:
        """Should serialize set as list."""
        result = serialize({1, 2, 3})
        assert isinstance(result, list)
        assert sorted(result) == [1, 2, 3]  # type: ignore[arg-type]

    def test_serialize_tuple(self) -> None:
        """Should serialize tuple as list."""
        result = serialize((1, 2, 3))
        assert result == [1, 2, 3]

    def test_serialize_dict(self) -> None:
        """Should serialize dict recursively."""
        uid = uuid.uuid4()
        result = serialize({"id": uid, "name": "test"})
        assert result == {"id": str(uid), "name": "test"}

    def test_serialize_pydantic_model(self) -> None:
        """Should serialize Pydantic model via model_dump."""
        msg = Message()
        result = serialize(msg)
        assert isinstance(result, dict)
        assert "__model__" in result

    def test_serialize_primitive(self) -> None:
        """Should serialize primitives via to_jsonable_python."""
        assert serialize("test") == "test"
        assert serialize(42) == 42
        assert serialize(3.14) == 3.14
        assert serialize(True) is True


class TestGetFieldSerializersMap:
    """Tests for get_field_serializers_map function."""

    def test_returns_empty_for_no_serializers(self) -> None:
        """Should return empty dict when no field serializers."""

        class NoSerializers(BaseModel):
            value: int

        result = get_field_serializers_map(NoSerializers)
        assert result == {}

    def test_returns_serializers(self) -> None:
        """Should extract field serializers from decorators."""
        # Message class has model_serializer but no field_serializers
        result = get_field_serializers_map(Message)
        # Message doesn't use field_serializer decorator, only model_serializer
        assert isinstance(result, dict)


class TestSerializeBaseModel:
    """Tests for serialize_base_model function."""

    def test_includes_model_marker(self) -> None:
        """Should include __model__ in output."""
        msg = Message()
        result = serialize_base_model(msg)
        assert "__model__" in result
        assert "Message" in result["__model__"]

    def test_serializes_all_fields(self) -> None:
        """Should serialize all non-excluded fields."""
        msg = UserMessage(content="Hello")
        result = serialize_base_model(msg)
        assert "content" in result
        assert "id" in result
        assert "display_type" in result

    def test_serializes_uuid_as_string(self) -> None:
        """Should serialize UUID fields as strings."""
        msg = Message()
        result = serialize_base_model(msg)
        assert isinstance(result["id"], str)


class TestSerializableBaseModel:
    """Tests for SerializableBaseModel class."""

    def test_inherits_from_basemodel(self) -> None:
        """Should inherit from Pydantic BaseModel."""
        assert issubclass(SerializableBaseModel, BaseModel)

    def test_allows_arbitrary_types(self) -> None:
        """Should have arbitrary_types_allowed config."""
        assert SerializableBaseModel.model_config.get("arbitrary_types_allowed") is True

    def test_model_dump_includes_marker(self) -> None:
        """model_dump() should include __model__ marker."""

        class TestModel(SerializableBaseModel):
            value: int

        model = TestModel(value=42)
        result = model.model_dump()
        assert "__model__" in result

    def test_deserialization_from_dict(self) -> None:
        """Should deserialize from dict with __model__."""
        msg = Message()
        data = msg.model_dump()
        # Remove __model__ to test regular dict handling
        data_without_model = {k: v for k, v in data.items() if k != "__model__"}
        reconstructed = Message(**data_without_model)
        assert reconstructed.display_type == msg.display_type


class TestImportClass:
    """Tests for import_class function."""

    def test_imports_known_class(self) -> None:
        """Should import class from module path."""
        cls = import_class("akgentic.core.messages.message.Message")
        assert cls is Message

    def test_raises_on_invalid_module(self) -> None:
        """Should raise ImportError for invalid module."""
        with pytest.raises(ModuleNotFoundError):
            import_class("nonexistent.module.Class")

    def test_raises_on_invalid_class(self) -> None:
        """Should raise AttributeError for invalid class."""
        with pytest.raises(AttributeError):
            import_class("akgentic.core.messages.message.NonexistentClass")


class TestIsUuidCanonical:
    """Tests for is_uuid_canonical function."""

    def test_valid_uuid(self) -> None:
        """Should return True for valid canonical UUID."""
        uid = uuid.uuid4()
        assert is_uuid_canonical(str(uid)) is True

    def test_invalid_string(self) -> None:
        """Should return False for non-UUID string."""
        assert is_uuid_canonical("not-a-uuid") is False

    def test_wrong_length(self) -> None:
        """Should return False for wrong length string."""
        assert is_uuid_canonical("12345") is False

    def test_non_string(self) -> None:
        """Should return False for non-string."""
        assert is_uuid_canonical(12345) is False
        assert is_uuid_canonical(None) is False


class TestDeserializeObject:
    """Tests for deserialize_object function."""

    def test_deserialize_primitive(self) -> None:
        """Should pass through primitives unchanged."""
        assert deserialize_object("test") == "test"
        assert deserialize_object(42) == 42
        assert deserialize_object(None) is None

    def test_deserialize_list(self) -> None:
        """Should recursively deserialize list."""
        result = deserialize_object([1, 2, {"key": "value"}])
        assert result == [1, 2, {"key": "value"}]

    def test_deserialize_dict(self) -> None:
        """Should recursively deserialize dict."""
        result = deserialize_object({"key": "value", "nested": {"a": 1}})
        assert result == {"key": "value", "nested": {"a": 1}}

    def test_deserialize_type(self) -> None:
        """Should deserialize __type__ dict to actual type."""
        result = deserialize_object({"__type__": "akgentic.core.messages.message.Message"})
        assert result is Message

    def test_deserialize_model(self) -> None:
        """Should deserialize __model__ dict to model instance."""
        msg = Message()
        data = msg.model_dump()
        result = deserialize_object(data)
        assert isinstance(result, Message)

    def test_deserialize_actor_address_without_context(self) -> None:
        """Should return ActorAddressProxy when no context for ActorAddress."""
        from akgentic.core.actor_address_impl import ActorAddressProxy

        addr_dict: ActorAddressDict = {
            "__actor_address__": True,
            "__actor_type__": "test.MockAgent",
            "agent_id": str(uuid.uuid4()),
            "name": "test-agent",
            "role": "assistant",
            "team_id": str(uuid.uuid4()),
            "squad_id": str(uuid.uuid4()),
            "user_message": False,
        }
        result = deserialize_object(addr_dict)
        # Without context, returns ActorAddressProxy (v1 behavior)
        assert isinstance(result, ActorAddressProxy)
        assert result.name == "test-agent"
        assert result.role == "assistant"

    def test_deserialize_with_canonical_uuid(self) -> None:
        """Should convert canonical UUIDs when flag is set."""
        uid = uuid.uuid4()
        result = deserialize_object(str(uid), canonical_uuid=True)
        assert result == uid
        assert isinstance(result, uuid.UUID)

    def test_deserialize_invalid_model_raises(self) -> None:
        """Should raise ValueError for invalid model data."""
        data = {
            "__model__": "akgentic.core.messages.message.UserMessage",
            # Missing required 'content' field
        }
        with pytest.raises(ValueError, match="Error deserializing model"):
            deserialize_object(data)

    def test_deserialize_set(self) -> None:
        """Should recursively deserialize set."""
        result = deserialize_object({1, 2, 3})
        assert result == {1, 2, 3}

    def test_deserialize_tuple(self) -> None:
        """Should recursively deserialize tuple."""
        result = deserialize_object((1, 2, 3))
        assert result == (1, 2, 3)


class TestDeserializeContext:
    """Tests for DeserializeContext abstract class."""

    def test_is_abstract(self) -> None:
        """Should be an abstract class."""
        with pytest.raises(TypeError):
            DeserializeContext()  # type: ignore[abstract]

    def test_can_implement(self) -> None:
        """Should be implementable."""

        class TestContext(DeserializeContext):
            def resolve_address(self, address_dict: ActorAddressDict) -> object:
                return {"resolved": True, **address_dict}

        ctx = TestContext()
        result = ctx.resolve_address(
            {
                "__actor_address__": True,
                "__actor_type__": "test.MockAgent",
                "agent_id": "12345678-1234-5678-1234-567812345678",
                "name": "test-agent",
                "role": "assistant",
                "team_id": "12345678-4321-8765-4321-876543218765",
                "squad_id": "11111111-2222-3333-4444-555555555555",
                "user_message": False,
            }
        )
        assert result["resolved"] is True  # type: ignore[index]


class TestMessageSerialization:
    """Integration tests for message serialization round-trip."""

    def test_message_round_trip(self) -> None:
        """Should serialize and deserialize Message."""
        original = Message()
        data = original.model_dump()
        reconstructed = deserialize_object(data)
        assert isinstance(reconstructed, Message)
        assert reconstructed.display_type == original.display_type

    def test_user_message_round_trip(self) -> None:
        """Should serialize and deserialize UserMessage."""
        original = UserMessage(content="Hello world")
        data = original.model_dump()
        reconstructed = deserialize_object(data)
        assert isinstance(reconstructed, UserMessage)
        assert reconstructed.content == "Hello world"
        assert reconstructed.display_type == "human"

    def test_received_message_serialization(self) -> None:
        """Should serialize ReceivedMessage with message_id."""
        from akgentic.core.messages.orchestrator import ReceivedMessage

        msg_id = uuid.uuid4()
        received = ReceivedMessage(message_id=msg_id)
        data = received.model_dump()
        assert "message_id" in data
        assert data["message_id"] == str(msg_id)
        assert "message" not in data


class TestPydanticDataclassSerialization:
    """Tests for pydantic dataclass serialization/deserialization (AC 1-6)."""

    def test_pydantic_dataclass_serialization_produces_base64(self) -> None:
        """AC-1: Pydantic dataclass with bytes serializes with __bytes__ tagged dict."""
        binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"  # PNG header bytes
        obj = FakeBinaryContent(data=binary_data, media_type="image/png")
        result = serialize(obj)

        assert isinstance(result, dict)
        # Pydantic dataclass should NOT have __model__ tag (AC-1)
        assert "__model__" not in result
        # Binary data should be a __bytes__ tagged dict with base64 content
        assert "data" in result
        assert isinstance(result["data"], dict)
        assert "__bytes__" in result["data"]
        decoded = base64.b64decode(result["data"]["__bytes__"])
        assert decoded == binary_data
        assert result["media_type"] == "image/png"

    def test_plain_dataclass_still_produces_model_tag(self) -> None:
        """AC-2: Plain dataclass serialization still produces __model__ tag (regression guard)."""
        obj = PlainEvent(name="test", count=42)
        result = serialize(obj)

        assert isinstance(result, dict)
        # Plain dataclass MUST have __model__ tag
        assert "__model__" in result
        assert "PlainEvent" in result["__model__"]
        assert result["name"] == "test"
        assert result["count"] == 42

    def test_pydantic_dataclass_round_trip_preserves_binary(self) -> None:
        """AC-5: Round-trip serialize then deserialize preserves binary data."""
        binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        original = FakeBinaryContent(data=binary_data, media_type="image/png")

        # Serialize (no __model__ tag, so wrap with __model__ for deserialization)
        serialized = serialize(original)
        assert isinstance(serialized, dict)

        # For round-trip, we need to add __model__ tag since pydantic dataclasses
        # are typically nested inside parent models that carry the tag
        serialized["__model__"] = serialize_type(original)
        reconstructed = deserialize_object(serialized)

        assert isinstance(reconstructed, FakeBinaryContent)
        assert reconstructed.data == binary_data
        assert reconstructed.media_type == "image/png"

    def test_plain_dataclass_round_trip_still_works(self) -> None:
        """AC-4: Plain dataclass round-trip still works (regression guard)."""
        original = PlainEvent(name="hello", count=99)
        serialized = serialize(original)
        assert isinstance(serialized, dict)
        assert "__model__" in serialized

        reconstructed = deserialize_object(serialized)
        assert isinstance(reconstructed, PlainEvent)
        assert reconstructed.name == "hello"
        assert reconstructed.count == 99

    def test_deserialize_pydantic_dataclass_with_bytes_tag(self) -> None:
        """AC-3: deserialize_object decodes __bytes__ tags and reconstructs pydantic dataclass."""
        binary_data = b"\xff\xd8\xff\xe0"  # JPEG header
        b64_data = base64.b64encode(binary_data).decode("ascii")

        serialized = {
            "__model__": serialize_type(FakeBinaryContent),
            "data": {"__bytes__": b64_data},
            "media_type": "image/jpeg",
        }

        result = deserialize_object(serialized)
        assert isinstance(result, FakeBinaryContent)
        assert result.data == binary_data
        assert result.media_type == "image/jpeg"

    def test_deserialize_basemodel_unchanged(self) -> None:
        """AC-4: BaseModel deserialization still uses model_class(**data)."""
        msg = Message()
        data = msg.model_dump()
        result = deserialize_object(data)
        assert isinstance(result, Message)
        assert result.display_type == msg.display_type

    def test_serialize_raw_bytes_produces_tagged_dict(self) -> None:
        """Raw bytes values serialize to {"__bytes__": "<base64>"}."""
        binary_data = b"\x89PNG\r\n"
        result = serialize(binary_data)
        assert isinstance(result, dict)
        assert "__bytes__" in result
        assert base64.b64decode(result["__bytes__"]) == binary_data

    def test_deserialize_bytes_tag_restores_bytes(self) -> None:
        """__bytes__ tagged dicts deserialize back to raw bytes."""
        binary_data = b"\xff\xd8\xff\xe0"
        tagged = {"__bytes__": base64.b64encode(binary_data).decode("ascii")}
        result = deserialize_object(tagged)
        assert isinstance(result, bytes)
        assert result == binary_data

    def test_bytes_round_trip_in_nested_dict(self) -> None:
        """Bytes inside a dict survive serialize/deserialize round-trip."""
        binary_data = b"\x89PNG\r\n\x1a\n"
        original = {"image": binary_data, "name": "test.png"}
        serialized = serialize(original)
        assert serialized["image"]["__bytes__"] is not None  # type: ignore[index]
        reconstructed = deserialize_object(serialized)
        assert reconstructed["image"] == binary_data
        assert reconstructed["name"] == "test.png"

    def test_malformed_bytes_tag_raises(self) -> None:
        """Malformed base64 in __bytes__ tag should raise binascii.Error."""
        import binascii

        tagged = {"__bytes__": "not-valid-base64!!!"}
        with pytest.raises(binascii.Error):
            deserialize_object(tagged)

    def test_plain_dataclass_containing_pydantic_dataclass_round_trip(self) -> None:
        """Realistic scenario: plain dataclass with nested pydantic dataclass containing bytes."""
        binary_data = b"\xff\xd8\xff\xe0\x00\x10JFIF"  # JPEG header
        original = PlainEventWithBinary(
            event_name="image_received",
            payload=FakeBinaryContent(data=binary_data, media_type="image/jpeg"),
        )

        # Serialize — asdict() flattens everything, but bytes get __bytes__ tags
        serialized = serialize(original)
        assert isinstance(serialized, dict)
        assert "__model__" in serialized

        # Deserialize — plain dataclass reconstructed, but nested pydantic dataclass
        # becomes a dict (pre-existing limitation of asdict flattening).
        # The key check: binary data survives as bytes, not base64 string.
        reconstructed = deserialize_object(serialized)
        assert isinstance(reconstructed, PlainEventWithBinary)
        assert reconstructed.event_name == "image_received"
        # payload is a dict (asdict flattening), but bytes are decoded
        assert reconstructed.payload["data"] == binary_data  # type: ignore[index]
        assert reconstructed.payload["media_type"] == "image/jpeg"  # type: ignore[index]

    def test_empty_bytes_round_trip(self) -> None:
        """Empty bytes should round-trip correctly."""
        result = serialize(b"")
        assert result == {"__bytes__": ""}
        assert deserialize_object(result) == b""
