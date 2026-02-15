"""Akgentic v2: Actor framework for agent-based systems.

Phase 1 provides core actor primitives with minimal dependencies (pydantic for serialization).
"""

from akgentic.actor_address import ActorAddress
from akgentic.actor_address_impl import (
    ActorAddressImpl,
    ActorAddressProxy,
    ActorAddressStopped,
)
from akgentic.actor_system_impl import (
    ActorSystemImpl,
    ExecutionContext,
    Statistics,
)
from akgentic.actor_system_impl import (
    ProxyWrapper as ActorProxyWrapper,
)
from akgentic.agent import Akgent, AkgentDeserializeContext, ProxyWrapper
from akgentic.agent_config import (
    AgentConfig,
    BaseConfig,
    ReadOnlyField,
)
from akgentic.agent_state import AkgentStateObserver, BaseState
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
from akgentic.orchestrator import Orchestrator, OrchestratorEventSubscriber
from akgentic.user_proxy import UserProxy
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

__version__ = "2.0.0-alpha.1"

# Alias for cleaner API
Akgent = Akgent

__all__ = [
    # Version
    "__version__",
    # Agent base class
    "Akgent",
    "Akgent",
    "AkgentDeserializeContext",
    "ProxyWrapper",
    # Actor system
    "ActorSystemImpl",
    "ExecutionContext",
    "ActorProxyWrapper",
    "Statistics",
    # Actor addressing
    "ActorAddress",
    "ActorAddressImpl",
    "ActorAddressProxy",
    "ActorAddressStopped",
    # Agent configuration
    "AgentConfig",
    "BaseConfig",
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
    # Orchestrator
    "Orchestrator",
    "OrchestratorEventSubscriber",
    # UserProxy
    "UserProxy",
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
