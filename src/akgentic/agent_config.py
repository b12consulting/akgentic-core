"""Agent configuration classes for initialization and restart.

Provides configuration structures for agent creation and internal framework use.
Migrated from akgentic-framework v1 with updated import paths.

Source: akgentic-framework/libs/akgentic/akgentic/core/akgent_config.py

Example:
    >>> config = BaseConfig(name="worker-1", role="processor")
    >>> config.model_dump()
    {'name': 'worker-1', 'role': 'processor', 'squad_id': None, '__model__': ...}

    >>> # Extend for custom configurations
    >>> class WorkerConfig(BaseConfig):
    ...     max_tasks: int = 10
    >>> WorkerConfig(name="w1", max_tasks=5)
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field

from akgentic.actor_address import ActorAddress
from akgentic.utils.serializer import SerializableBaseModel


def ReadOnlyField(**kwargs: Any) -> Any:  # noqa: N802
    """Create a Pydantic Field marked as read-only in JSON schema.

    Sets json_schema_extra with readOnly=True for schema generation,
    useful for fields that should not be modified after creation.

    Args:
        **kwargs: All keyword arguments passed to pydantic.Field.

    Returns:
        A Pydantic Field with readOnly schema metadata.

    Example:
        >>> class Model(BaseModel):
        ...     id: str = ReadOnlyField(default="auto")
    """
    kwargs.setdefault("json_schema_extra", {"readOnly": True})
    return Field(**kwargs)


class BaseConfig(SerializableBaseModel):
    """Base configuration for agent initialization.

    This class provides common configuration fields that all agents
    can use. Custom agent types can extend this class to add
    domain-specific configuration.

    Attributes:
        name: Human-readable agent name for logging and identification.
        role: Agent role/type for categorization and routing.
        squad_id: Team/squad identifier for grouping related agents.

    Example:
        >>> config = BaseConfig(name="worker-1", role="processor")
        >>> config.model_dump()
        {'name': 'worker-1', 'role': 'processor', 'squad_id': None, ...}
    """

    name: str | None = None
    role: str | None = None
    squad_id: uuid.UUID | None = None


class PrivateConfig(SerializableBaseModel):
    """Internal framework configuration for agent management.

    Attributes:
        team_id: Required team identifier for coordination.
        user_id: Optional user identifier for multi-tenant scenarios.
        user_email: Optional user email for notifications.
        parent: ActorAddress of the parent agent in hierarchy.
        orchestrator: ActorAddress of the orchestrating agent.
    """

    team_id: uuid.UUID
    user_id: str | None = None
    user_email: str | None = None
    parent: ActorAddress | None = None
    orchestrator: ActorAddress | None = None


# Type alias for extensibility (AC: 2)
AgentConfig = BaseConfig
"""Type alias for agent configuration.

Allows code to reference AgentConfig as the standard configuration type
while BaseConfig remains the concrete implementation.
"""
