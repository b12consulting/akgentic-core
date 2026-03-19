"""Serialization utilities for actor messages.

Provides SerializableBaseModel base class and serialization functions
for proper handling of UUID, datetime, ActorAddress, and nested Pydantic models.

Source: Preserves v1 serialization behavior from akgentic-framework.
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationInfo, model_serializer, model_validator
from pydantic_core import to_jsonable_python

from akgentic.core.actor_address import ActorAddress
from akgentic.core.utils.deserializer import ActorAddressDict, deserialize_object


def serialize_type(value: type[Any] | Any) -> str:
    """Serialize a type to its module path and name.

    Args:
        value: A type or instance to serialize.

    Returns:
        String in format "module.ClassName".
    """
    if isinstance(value, type):
        return f"{value.__module__}.{value.__name__}"
    return f"{value.__class__.__module__}.{value.__class__.__name__}"


def serialize(value: Any) -> dict[str, Any] | list[Any] | str | None | ActorAddressDict:
    """Recursively serialize values, adding tagged-dict metadata where needed.

    Handles UUID, datetime, ActorAddress, bytes, types, lists, dicts, BaseModel,
    and dataclasses with proper serialization. Special tagged dicts:
    - ``__model__``: Pydantic model or plain dataclass class path
    - ``__type__``: Python type class path
    - ``__bytes__``: Base64-encoded binary data

    Args:
        value: The value to serialize.

    Returns:
        Serialized representation of the value.
    """
    if value is None:
        return None
    elif isinstance(value, uuid.UUID):
        return str(value)
    elif isinstance(value, ActorAddress):
        return value.serialize()
    elif isinstance(value, datetime):
        return value.isoformat()
    elif isinstance(value, bytes):
        return {"__bytes__": base64.b64encode(value).decode("ascii")}
    elif isinstance(value, type):
        return {"__type__": serialize_type(value)}
    elif isinstance(value, (list, set, tuple)):
        return [serialize(item) for item in value]
    elif isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items()}
    elif isinstance(value, BaseModel):
        model_dict: dict[str, Any] = value.model_dump()
        return model_dict
    elif is_dataclass(value) and not isinstance(value, type):
        if hasattr(value, "__pydantic_serializer__"):
            # Pydantic dataclass: manually serialize with base64 for bytes fields
            # to avoid UnicodeDecodeError on non-UTF-8 binary data (PNG, JPEG, etc.)
            result: dict[str, Any] = {}
            for f in fields(value):
                result[f.name] = serialize(getattr(value, f.name))
            return result
        # Plain dataclass: keep current __model__ tag approach
        data = asdict(value)
        data["__model__"] = serialize_type(value)
        return serialize(data)
    else:
        return to_jsonable_python(value)  # type: ignore[no-any-return]


def get_field_serializers_map(model_class: type[BaseModel]) -> dict[str, Any]:
    """Extract field serializers from a Pydantic model class.

    Args:
        model_class: The Pydantic model class to inspect.

    Returns:
        Dictionary mapping field names to their serializer functions.
    """
    field_serializers_map: dict[str, Any] = {}
    decorators = getattr(model_class, "__pydantic_decorators__", None)
    if decorators and hasattr(decorators, "field_serializers"):
        for decorator_info in decorators.field_serializers.values():
            for field_name in decorator_info.info.fields:
                field_serializers_map[field_name] = decorator_info.func
    return field_serializers_map


def serialize_base_model(cls: BaseModel) -> dict[str, Any]:
    """Add __model__ metadata after field serialization.

    Args:
        cls: The BaseModel instance to serialize.

    Returns:
        Dictionary with serialized fields and __model__ metadata.
    """
    data: dict[str, Any] = {}
    field_serializers_map = get_field_serializers_map(cls.__class__)

    for field_name, field_info in cls.__class__.model_fields.items():
        if field_info.exclude:
            continue
        value = getattr(cls, field_name, None)

        if field_name in field_serializers_map:
            serializer_func = field_serializers_map[field_name]
            value = serializer_func(cls, value)

        data[field_name] = serialize(value)

    data["__model__"] = serialize_type(cls)
    return data


class SerializableBaseModel(BaseModel):
    """Base class for models that need proper serialization of UUID, ActorAddress, etc.

    Provides automatic serialization and deserialization of complex types
    including UUID, datetime, ActorAddress, and nested Pydantic models.

    Attributes:
        model_config: Pydantic configuration allowing arbitrary types.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @model_validator(mode="before")
    @classmethod
    def deserialize_types(cls, data: Any, info: ValidationInfo) -> Any:
        """Deserialize custom type representations.

        Args:
            data: Input data to deserialize.
            info: Pydantic validation info with context.

        Returns:
            Deserialized data suitable for model construction.
        """
        context = info.context if info.context else None
        module_path_name = serialize_type(cls)
        if isinstance(data, dict) and data.get("__model__") == module_path_name:
            return {
                key: deserialize_object(value, context)
                for key, value in data.items()
                if key != "__model__"
            }
        return deserialize_object(data, context)

    @model_serializer
    def serialize_model(self) -> dict[str, Any]:
        """Serialize with proper handling of UUID, ActorAddress, datetime, and nested models.

        Returns:
            Dictionary with serialized fields and __model__ metadata.
        """
        return serialize_base_model(self)
