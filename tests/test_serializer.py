"""Tests for serialization utilities.

Tests serialize functions, SerializableBaseModel, and deserialize_object.
"""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from akgentic.messages.message import Message, UserMessage
from akgentic.utils.deserializer import (
    ActorAddressDict,
    DeserializeContext,
    deserialize_object,
    import_class,
    is_uuid_canonical,
)
from akgentic.utils.serializer import (
    SerializableBaseModel,
    get_field_serializers_map,
    serialize,
    serialize_base_model,
    serialize_type,
)


class TestSerializeType:
    """Tests for serialize_type function."""

    def test_serializes_class(self) -> None:
        """Should serialize class to module.ClassName."""
        result = serialize_type(Message)
        assert result == "akgentic.messages.message.Message"

    def test_serializes_instance(self) -> None:
        """Should serialize instance to module.ClassName."""
        msg = Message()
        result = serialize_type(msg)
        assert result == "akgentic.messages.message.Message"

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
        cls = import_class("akgentic.messages.message.Message")
        assert cls is Message

    def test_raises_on_invalid_module(self) -> None:
        """Should raise ImportError for invalid module."""
        with pytest.raises(ModuleNotFoundError):
            import_class("nonexistent.module.Class")

    def test_raises_on_invalid_class(self) -> None:
        """Should raise AttributeError for invalid class."""
        with pytest.raises(AttributeError):
            import_class("akgentic.messages.message.NonexistentClass")


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
        result = deserialize_object({"__type__": "akgentic.messages.message.Message"})
        assert result is Message

    def test_deserialize_model(self) -> None:
        """Should deserialize __model__ dict to model instance."""
        msg = Message()
        data = msg.model_dump()
        result = deserialize_object(data)
        assert isinstance(result, Message)

    def test_deserialize_actor_address_without_context(self) -> None:
        """Should return ActorAddressProxy when no context for ActorAddress."""
        from akgentic.actor_address_impl import ActorAddressProxy

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
            "__model__": "akgentic.messages.message.UserMessage",
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
            {"__actor_address__": True, "id": "123", "name": "test"}
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

    def test_nested_message_serialization(self) -> None:
        """Should serialize nested messages."""
        from akgentic.messages.orchestrator import ReceivedMessage

        inner = UserMessage(content="Inner message")
        outer = ReceivedMessage(message=inner)
        data = outer.model_dump()
        assert "message" in data
        assert isinstance(data["message"], dict)
        assert data["message"]["content"] == "Inner message"
