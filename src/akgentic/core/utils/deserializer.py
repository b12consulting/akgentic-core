"""Deserialization utilities for actor messages.

Provides DeserializeContext abstract class and deserialize_object function
for reconstructing serialized messages with proper type handling.

Source: Preserves v1 deserialization behavior from akgentic-framework.
"""

from __future__ import annotations

import base64
import logging
import sys
import uuid
from abc import ABC, abstractmethod
from dataclasses import is_dataclass
from importlib import import_module
from typing import Any, TypedDict, cast

from pydantic import PydanticUserError, TypeAdapter

logger = logging.getLogger(__name__)


class ActorAddressDict(TypedDict):
    """TypedDict for serialized ActorAddress representation.

    Contains all metadata fields needed for Phase 3 remote communication
    and address reconstruction during deserialization.

    Attributes:
        __actor_address__: Marker for deserialization dispatch.
        __actor_type__: Fully qualified class name for reconstruction.
        agent_id: UUID as string for unique agent identification.
        name: Agent name from configuration.
        role: Agent role from configuration.
        team_id: Team UUID as string for team identification.
        squad_id: Squad UUID as string for squad identification.
        is_user_proxy: Whether the actor is a UserProxy (or subclass).
    """

    __actor_address__: bool
    __actor_type__: str
    agent_id: str
    name: str
    role: str
    team_id: str
    squad_id: str
    is_user_proxy: bool


class DeserializeContext(ABC):
    """Abstract base class for deserialization context.

    Provides interface for resolving ActorAddress references during
    message deserialization. Implementations handle address resolution
    based on the specific actor system configuration.
    """

    @abstractmethod
    def resolve_address(self, address_dict: ActorAddressDict) -> Any:
        """Resolve an address_dict to an ActorAddress.

        Args:
            address_dict: Serialized address dictionary with id and name.

        Returns:
            Resolved ActorAddress instance.
        """
        ...


def import_class(class_path: str) -> type[Any]:
    """Dynamically import a class from the given path.

    Args:
        class_path: Full module path and class name (e.g., "module.ClassName").

    Returns:
        The imported class.

    Raises:
        ImportError: If module cannot be imported.
        AttributeError: If class not found in module.
    """
    module_path, class_name = class_path.rsplit(".", 1)
    module = import_module(module_path)
    return getattr(module, class_name)  # type: ignore[no-any-return]


class UnresolvableClassError(ValueError):
    """A ``__model__`` / ``__type__`` tag names a class path that no longer exists.

    A ``ValueError``, so every caller that isolates a bad record on ``ValueError`` is unchanged.
    It has a type of its own so the list branch can drop exactly this failure and nothing else.
    """


def _is_missing_path(class_path: str, error: ImportError | AttributeError) -> bool:
    """Whether *error* means the class path is gone, not that its module failed to import.

    A deleted class shows as a ``ModuleNotFoundError`` naming the tagged module or one of its
    parents, or as an ``AttributeError`` from a module that did import. A missing third-party
    package or a broken module body is a broken environment, and must stay loud.
    """
    module_path = class_path.rsplit(".", 1)[0]
    if isinstance(error, ModuleNotFoundError):
        missing = error.name or ""
        return module_path == missing or module_path.startswith(f"{missing}.")
    # A module whose own import raised is removed from sys.modules; one that imported stays.
    return isinstance(error, AttributeError) and module_path in sys.modules


def _resolve_tagged_class(class_path: str, *, marker: str) -> type[Any]:
    """Resolve a ``__model__`` / ``__type__`` tag; a path that is gone is UnresolvableClassError."""
    try:
        return import_class(class_path)
    except (ImportError, AttributeError) as e:
        if not _is_missing_path(class_path, e):
            raise
        raise UnresolvableClassError(f"Cannot resolve {marker} {class_path!r}: {e}") from e


_type_adapter_cache: dict[type[Any], TypeAdapter[Any] | None] = {}


def _get_type_adapter(cls: type[Any]) -> TypeAdapter[Any] | None:
    """Return a cached TypeAdapter for *cls*, or None if the type is not fully defined."""
    try:
        return _type_adapter_cache[cls]
    except KeyError:
        try:
            ta: TypeAdapter[Any] | None = TypeAdapter(cls)
        except Exception:
            # TypeAdapter fails when annotations are unresolved
            # (e.g. TYPE_CHECKING imports with `from __future__ import annotations`).
            ta = None
        _type_adapter_cache[cls] = ta
        return ta


def is_uuid_canonical(val: Any) -> bool:
    """Check if string is valid UUID in canonical format.

    Args:
        val: Value to check.

    Returns:
        True if val is a string in canonical UUID format (36 chars with hyphens).
    """
    if not isinstance(val, str) or len(val) != 36:
        return False
    try:
        return str(uuid.UUID(val)) == val
    except ValueError:
        return False


def deserialize_object(
    obj: dict[str, Any] | list[Any] | set[Any] | tuple[Any, ...] | Any,
    context: DeserializeContext | None = None,
    canonical_uuid: bool = False,
) -> Any:
    """Recursively deserialize Pydantic models from dictionaries containing tagged-dict markers.

    Handles special markers:
    - __actor_address__: Reconstructs ActorAddress via context or proxy
    - __bytes__: Decodes base64 string back to raw bytes
    - __type__: Imports and returns the type
    - __model__: Reconstructs Pydantic model or dataclass

    Args:
        obj: Object to deserialize (dict, list, set, tuple, or primitive).
        context: Optional deserialization context for address resolution.
        canonical_uuid: If True, convert canonical UUID strings to uuid.UUID.

    Returns:
        Deserialized object with proper types restored.

    Raises:
        UnresolvableClassError: A ``ValueError`` raised when a __model__ / __type__ tag
            outside any list names a class path that no longer exists. Inside a list, the
            element is dropped with a WARNING instead.
        ValueError: If model construction fails.
    """
    if isinstance(obj, dict):
        if "__actor_address__" in obj:
            address_dict = cast(ActorAddressDict, obj)
            if context is None:
                # Import here to avoid circular imports at module level
                from akgentic.core.actor_address_impl import ActorAddressProxy

                return ActorAddressProxy(address_dict)
            return context.resolve_address(address_dict)

        if "__bytes__" in obj:
            return base64.b64decode(obj["__bytes__"])

        if "__type__" in obj:
            return _resolve_tagged_class(obj["__type__"], marker="__type__")

        if "__model__" in obj:
            model_class = _resolve_tagged_class(obj["__model__"], marker="__model__")
            deserialized_data = {
                key: deserialize_object(value, context)
                for key, value in obj.items()
                if key != "__model__"
            }
            try:
                if is_dataclass(model_class) and (adapter := _get_type_adapter(model_class)):
                    # Dataclasses: use TypeAdapter for proper type coercion
                    # (datetime from ISO strings, nested unions, etc.).
                    # Falls back to direct construction when annotations are
                    # unresolvable (e.g. TYPE_CHECKING-guarded imports).
                    try:
                        model: object = adapter.validate_python(deserialized_data)
                    except PydanticUserError:
                        model = model_class(**deserialized_data)
                else:
                    # BaseModel: coercion handled by Pydantic validators.
                    model = model_class(**deserialized_data)
            except Exception as e:
                raise ValueError(
                    f"Error deserializing model {model_class}: {e}\nData: {deserialized_data}"
                ) from e
            return model

        return {key: deserialize_object(value, context) for key, value in obj.items()}

    elif isinstance(obj, list):
        return _deserialize_list(obj, context)

    elif isinstance(obj, set):
        return {deserialize_object(item, context) for item in obj}

    elif isinstance(obj, tuple):
        return tuple(deserialize_object(item, context) for item in obj)

    elif canonical_uuid and is_uuid_canonical(obj):
        return uuid.UUID(obj)

    else:
        return obj


def _deserialize_list(items: list[Any], context: DeserializeContext | None) -> list[Any]:
    """Deserialize each element; drop one whose class, or a class nested in it, is gone."""
    kept: list[Any] = []
    for index, item in enumerate(items):
        try:
            kept.append(deserialize_object(item, context))
        except UnresolvableClassError as e:
            tag = item.get("__model__", item.get("__type__")) if isinstance(item, dict) else None
            logger.warning(
                "Dropping list element %d (%s) that cannot be rehydrated: %s", index, tag, e
            )
    return kept
