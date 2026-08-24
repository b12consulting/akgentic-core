"""ActorAddress abstraction for agent references and communication.

Provides an abstract interface for agent addressing that decouples agent identity
from the underlying actor implementation (Pykka). Supports serialization for
Phase 3 remote communication and rich metadata access.

Phase 3 Extensibility:
    This module defines the ActorAddress ABC that can be extended for remote
    communication. Future implementations may include:
    - ActorAddressRemote: HTTP-based remote actor communication
    - ActorAddressRedis: Redis pub/sub based communication

Example:
    >>> # Using ActorAddress in an Agent (future Agent class)
    >>> class Agent(pykka.ThreadingActor):
    ...     @property
    ...     def myAddress(self) -> ActorAddress:
    ...         return ActorAddressImpl(self.actor_ref)
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from akgentic.core.utils.deserializer import ActorAddressDict


class ActorAddress(ABC):
    """Abstract base class for actor address/reference.

    Provides a unified interface for agent identification and communication
    that is independent of the underlying actor system (Pykka). All agent
    references should use this abstraction rather than raw ActorRef.

    The address provides rich metadata (name, role, team_id, squad_id) without
    exposing internal implementation details. Implementations handle different
    scenarios: live local actors, deserialized proxy addresses, and stopped actors.

    Attributes:
        agent_id: Unique identifier for the agent.
        name: Agent name from configuration.
        role: Agent role from configuration.
        team_id: Team identifier from configuration.
        squad_id: Squad identifier from configuration.
        is_user_proxy: Whether the addressed actor is a UserProxy (or subclass).
    """

    @property
    @abstractmethod
    def agent_id(self) -> uuid.UUID:
        """Unique identifier for this agent.

        Returns:
            UUID uniquely identifying this agent instance.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent name from configuration.

        Returns:
            Human-readable name for this agent.
        """
        ...

    @property
    @abstractmethod
    def role(self) -> str:
        """Agent role from configuration.

        Returns:
            Role string describing agent's function.
        """
        ...

    @property
    @abstractmethod
    def team_id(self) -> uuid.UUID:
        """Team identifier from configuration.

        Returns:
            UUID of the team this agent belongs to.
        """
        ...

    @property
    @abstractmethod
    def squad_id(self) -> uuid.UUID | None:
        """Squad identifier from configuration.

        Returns:
            UUID of the squad this agent belongs to, or None if not set.
        """
        ...

    @property
    @abstractmethod
    def is_user_proxy(self) -> bool:
        """Whether the addressed actor is a UserProxy, by type rather than by role.

        Returns:
            True if the actor is a ``UserProxy`` instance or an instance of any
            of its subclasses.
        """
        ...

    @abstractmethod
    def send(self, recipient: ActorAddress, message: Any) -> None:
        """Send a message from this agent to the recipient.

        Args:
            recipient: The target actor to receive the message, or None if unspecified.
            message: The message to send (typically a Message subclass).

        Raises:
            RuntimeError: If this address cannot send messages (e.g., proxy address).
        """
        ...

    def tell(self, message: Any) -> None:
        """Deliver *message* to this actor's inbox without waiting for a reply.

        Unlike :meth:`send`, which routes a message *from* this actor to a
        recipient, ``tell`` delivers *to* this actor.

        Concrete rather than abstract on purpose. ``ActorAddress`` is subclassed
        by test fakes across several packages, and an abstract method added here
        breaks every one of them at instantiation — in repositories that cannot
        be fixed in the same change. Addresses that can deliver override this;
        the rest inherit a refusal that names them.

        Args:
            message: The message to deliver.

        Raises:
            RuntimeError: If this address cannot deliver messages.
        """
        raise RuntimeError(f"{type(self).__name__} {self.name} cannot deliver messages")

    def ask(self, message: Any, timeout: float | None = None) -> Any:
        """Deliver *message* to this actor and block until it has been handled.

        Concrete for the same reason as :meth:`tell`.

        Args:
            message: The message to deliver.
            timeout: Seconds to wait for the reply; ``None`` waits forever.

        Returns:
            Whatever the actor's handler returned.

        Raises:
            RuntimeError: If this address cannot deliver messages.
        """
        raise RuntimeError(f"{type(self).__name__} {self.name} cannot deliver messages")

    @abstractmethod
    def is_alive(self) -> bool:
        """Check if this actor is still running.

        Returns:
            True if the actor is alive and can receive messages, False otherwise.
        """
        ...

    @abstractmethod
    def serialize(self) -> ActorAddressDict:
        """Serialize this address to a dictionary for transport.

        Produces an ActorAddressDict suitable for JSON serialization
        and Phase 3 remote communication.

        Returns:
            Dictionary representation of this address.
        """
        ...

    @abstractmethod
    def __repr__(self) -> str:
        """String representation for debugging.

        Returns:
            String showing class name, agent name, and ID.
        """
        ...
