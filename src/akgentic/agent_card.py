"""Agent profile cards for team capability discovery.

AgentCards describe available agent profiles/roles in a team, enabling
dynamic discovery of capabilities and agent creation patterns.
"""

from __future__ import annotations

from typing import Any

from akgentic.agent_config import BaseConfig
from akgentic.utils.serializer import SerializableBaseModel


class AgentCard(SerializableBaseModel):
    """Describes an agent profile/role available in the team.

    AgentCards form a capability catalog, allowing agents to discover
    what profiles exist and how to work with them. This is not instance
    tracking—it's a profile directory.

    Example:
        >>> card = AgentCard(
        ...     role="ResearchAgent",
        ...     description="Performs web research and data gathering",
        ...     skills=["web_search", "pdf_extraction"],
        ...     agent_class="examples.multi_agent.ResearchAgent",
        ...     configuration=BaseConfig(name="research", role="ResearchAgent"),
        ...     routes_to=["WriterAgent", "AnalystAgent"]
        ... )
        >>> # Now other agents can discover this profile and its config
        >>> print(card.skills)
        ['web_search', 'pdf_extraction']
        >>> card.can_route_to("WriterAgent")
        True

    Attributes:
        role: Agent role/type identifier (e.g., "ResearchAgent")
        description: Human-readable description of what this agent does
        skills: List of capabilities this agent provides
        agent_class: Fully qualified class name for dynamic instantiation
        configuration: Default BaseConfig (or subclass) for this profile
        routes_to: List of roles this agent can send requests to.
                   Empty list means can route to any role (no restrictions).
                   Agents can always respond to requests regardless of this field.
        metadata: Extensible key-value storage for custom attributes
    """

    role: str
    description: str
    skills: list[str]
    agent_class: str
    configuration: BaseConfig | dict[str, Any] = {}
    routes_to: list[str] = []
    metadata: dict[str, Any] = {}

    def get_config(self) -> BaseConfig:
        """Get configuration as BaseConfig instance.

        Returns:
            BaseConfig instance (converts dict if needed)
        """
        if isinstance(self.configuration, BaseConfig):
            return self.configuration
        elif isinstance(self.configuration, dict):
            return BaseConfig(**self.configuration)
        return BaseConfig()

    def has_skill(self, skill: str) -> bool:
        """Check if this profile has a specific skill.

        Args:
            skill: Skill to check for

        Returns:
            True if skill is in the profile's skill list
        """
        return skill in self.skills

    def can_route_to(self, role: str) -> bool:
        """Check if this profile can send requests to a specific role.

        An empty routes_to list means no restrictions (can route to anyone).
        Otherwise, the target role must be in the routes_to list.

        Note: Agents can always RESPOND to requests from any role.
        This only controls which roles an agent can proactively SEND to.

        Args:
            role: Target role to check routing permission for

        Returns:
            True if this agent profile can send requests to the target role
        """
        if not self.routes_to:
            return True  # No restrictions - can route to any role
        return role in self.routes_to
