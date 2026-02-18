"""Akgentic v2: Actor framework for agent-based systems.

Phase 1 provides core actor primitives with minimal dependencies (pydantic for serialization).
"""

# Extend __path__ to allow sub-packages from other workspace distributions
# (e.g. akgentic-llm's akgentic.llm) to be discovered as part of this namespace.
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)  # type: ignore[assignment]

from akgentic.actor_address import ActorAddress
from akgentic.actor_address_impl import (
    ActorAddressImpl,
    ActorAddressProxy,
    ActorAddressStopped,
)
from akgentic.actor_system_impl import (
    ActorSystem,
    ExecutionContext,
    Statistics,
)
from akgentic.agent import Akgent, AkgentDeserializeContext
from akgentic.agent_config import (
    AgentConfig,
    BaseConfig,
)
from akgentic.agent_state import AkgentStateObserver, BaseState
from akgentic.orchestrator import Orchestrator, OrchestratorEventSubscriber
from akgentic.user_proxy import UserProxy

__version__ = "1.0.0-alpha.1"

__all__ = [
    # Version
    "__version__",
    # Agent base class and proxies
    "Akgent",
    "AkgentDeserializeContext",
    # Actor system
    "ActorSystem",
    "ExecutionContext",
    "Statistics",
    # Actor addressing
    "ActorAddress",
    "ActorAddressImpl",
    "ActorAddressProxy",
    "ActorAddressStopped",
    # Agent configuration
    "AgentConfig",
    "BaseConfig",
    # Agent state
    "AkgentStateObserver",
    "BaseState",
    # Orchestrator
    "Orchestrator",
    "OrchestratorEventSubscriber",
    # UserProxy
    "UserProxy",
]
