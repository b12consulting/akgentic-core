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
from akgentic.orchestrator import Orchestrator, OrchestratorEventSubscriber
from akgentic.user_proxy import UserProxy

__version__ = "2.0.0-alpha.1"

__all__ = [
    # Version
    "__version__",
    # Agent base class and proxies
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
    # Orchestrator
    "Orchestrator",
    "OrchestratorEventSubscriber",
    # UserProxy
    "UserProxy",
]
