"""Akgentic v2: Actor framework for agent-based systems.

Phase 1 provides core actor primitives with minimal dependencies (pydantic for serialization).
"""

__version__ = "2.0.0-alpha.1"

# Actor addressing
from akgentic.actor_address import ActorAddress
from akgentic.actor_address_impl import (
    ActorAddressImpl,
    ActorAddressProxy,
    ActorAddressStopped,
)

# Agent configuration
from akgentic.agent_config import (
    AgentConfig,
    BaseConfig,
    PrivateConfig,
    ReadOnlyField,
)

# Agent state
from akgentic.agent_state import AkgentStateObserver, BaseState

# Message primitives
from akgentic.messages.message import (
    Message,
    ResultMessage,
    StopRecursively,
    UserMessage,
    date_time_factory,
)
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

# Serialization utilities
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

__all__ = [
    # Version
    "__version__",
    # Actor addressing
    "ActorAddress",
    "ActorAddressImpl",
    "ActorAddressProxy",
    "ActorAddressStopped",
    # Agent configuration
    "AgentConfig",
    "BaseConfig",
    "PrivateConfig",
    "ReadOnlyField",
    # Agent state
    "AkgentStateObserver",
    "BaseState",
    # Base message
    "Message",
    "ResultMessage",
    "StopRecursively",
    "UserMessage",
    "date_time_factory",
    # Orchestrator messages
    "ContextChangedMessage",
    "ErrorMessage",
    "ProcessedMessage",
    "ReceivedMessage",
    "SentMessage",
    "StartMessage",
    "StateChangedMessage",
    "StopMessage",
    "ToolUpdateMessage",
    # Serialization
    "ActorAddressDict",
    "DeserializeContext",
    "SerializableBaseModel",
    "deserialize_object",
    "get_field_serializers_map",
    "import_class",
    "is_uuid_canonical",
    "serialize",
    "serialize_base_model",
    "serialize_type",
]
