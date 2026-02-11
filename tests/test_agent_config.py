"""Tests for agent configuration classes.

Tests BaseConfig, PrivateConfig, AgentConfig, and ReadOnlyField
per Story 1.4 acceptance criteria.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from akgentic import ActorAddressProxy
from akgentic.agent_config import (
    AgentConfig,
    BaseConfig,
    PrivateConfig,
    ReadOnlyField,
)


class TestBaseConfig:
    """Tests for BaseConfig class (AC: 1, 5)."""

    def test_default_instantiation(self) -> None:
        """BaseConfig() creates instance with all None defaults."""
        config = BaseConfig()
        assert config.name is None
        assert config.role is None
        assert config.squad_id is None

    def test_explicit_values(self) -> None:
        """BaseConfig accepts explicit field values."""
        config = BaseConfig(name="test-agent", role="worker")
        assert config.name == "test-agent"
        assert config.role == "worker"
        assert config.squad_id is None

    def test_with_squad_id(self) -> None:
        """BaseConfig accepts squad_id UUID."""
        squad = uuid.uuid4()
        config = BaseConfig(name="agent", role="processor", squad_id=squad)
        assert config.squad_id == squad

    def test_serialization_to_dict(self) -> None:
        """BaseConfig serializes to dict for StartMessage payload (AC: 7)."""
        squad = uuid.uuid4()
        config = BaseConfig(name="worker-1", role="processor", squad_id=squad)
        data = config.model_dump()
        assert isinstance(data, dict)
        assert data["name"] == "worker-1"
        assert data["role"] == "processor"
        # UUID serialized as string
        assert "__model__" in data  # SerializableBaseModel adds this


class TestCustomConfig:
    """Tests for extending BaseConfig (AC: 2, 5)."""

    def test_custom_config_extends_base(self) -> None:
        """Custom config classes can extend BaseConfig with additional fields."""

        class WorkerConfig(BaseConfig):
            max_tasks: int = 10
            timeout_seconds: float = 30.0

        config = WorkerConfig(name="worker", max_tasks=5)
        assert config.name == "worker"
        assert config.max_tasks == 5
        assert config.timeout_seconds == 30.0
        assert config.role is None

    def test_custom_config_serialization(self) -> None:
        """Custom configs serialize including extended fields."""

        class WorkerConfig(BaseConfig):
            max_tasks: int = 10

        config = WorkerConfig(name="worker", max_tasks=5)
        data = config.model_dump()
        assert data["name"] == "worker"
        assert data["max_tasks"] == 5


class TestPrivateConfig:
    """Tests for PrivateConfig class (AC: 3, 5, 8)."""

    def test_requires_team_id(self) -> None:
        """PrivateConfig requires team_id - raises ValidationError if missing."""
        with pytest.raises(ValidationError) as exc_info:
            PrivateConfig()  # type: ignore[call-arg]
        assert "team_id" in str(exc_info.value)

    def test_with_team_id_only(self) -> None:
        """PrivateConfig accepts team_id with all other fields as None."""
        team = uuid.uuid4()
        config = PrivateConfig(team_id=team)
        assert config.team_id == team
        assert config.user_id is None
        assert config.user_email is None
        assert config.parent is None
        assert config.orchestrator is None

    def test_with_all_optional_fields(self) -> None:
        """PrivateConfig accepts all optional fields."""
        team = uuid.uuid4()
        config = PrivateConfig(
            team_id=team,
            user_id="user-123",
            user_email="user@example.com",
        )
        assert config.team_id == team
        assert config.user_id == "user-123"
        assert config.user_email == "user@example.com"

    def test_with_actor_address_parent(self) -> None:
        """PrivateConfig.parent accepts ActorAddress (AC: 8)."""
        team = uuid.uuid4()
        parent_address = ActorAddressProxy({
            "__actor_address__": True,
            "__actor_type__": "test.ParentAgent",
            "agent_id": str(uuid.uuid4()),
            "name": "parent-agent",
            "role": "supervisor",
            "team_id": str(team),
            "squad_id": None,
            "user_message": False,
        })
        config = PrivateConfig(team_id=team, parent=parent_address)
        assert config.parent is parent_address
        assert config.parent.name == "parent-agent"

    def test_with_actor_address_orchestrator(self) -> None:
        """PrivateConfig.orchestrator accepts ActorAddress (AC: 8)."""
        team = uuid.uuid4()
        orch_address = ActorAddressProxy({
            "__actor_address__": True,
            "__actor_type__": "test.Orchestrator",
            "agent_id": str(uuid.uuid4()),
            "name": "orchestrator",
            "role": "coordinator",
            "team_id": str(team),
            "squad_id": None,
            "user_message": True,
        })
        config = PrivateConfig(team_id=team, orchestrator=orch_address)
        assert config.orchestrator is orch_address
        assert config.orchestrator.role == "coordinator"

    def test_serialization_to_dict(self) -> None:
        """PrivateConfig serializes to dict (AC: 7)."""
        team = uuid.uuid4()
        config = PrivateConfig(
            team_id=team,
            user_id="user-456",
        )
        data = config.model_dump()
        assert isinstance(data, dict)
        assert data["user_id"] == "user-456"
        assert "__model__" in data


class TestAgentConfigAlias:
    """Tests for AgentConfig type alias (AC: 2)."""

    def test_agent_config_is_base_config(self) -> None:
        """AgentConfig type alias resolves to BaseConfig."""
        assert AgentConfig is BaseConfig

    def test_agent_config_instantiation(self) -> None:
        """AgentConfig can be used as BaseConfig."""
        config: AgentConfig = AgentConfig(name="agent", role="worker")
        assert isinstance(config, BaseConfig)


class TestReadOnlyField:
    """Tests for ReadOnlyField helper function."""

    def test_readonly_field_sets_schema_extra(self) -> None:
        """ReadOnlyField sets json_schema_extra with readOnly=True."""
        from pydantic import BaseModel

        class TestModel(BaseModel):
            value: str = ReadOnlyField(default="test")

        schema = TestModel.model_json_schema()
        assert schema["properties"]["value"].get("readOnly") is True

    def test_readonly_field_preserves_kwargs(self) -> None:
        """ReadOnlyField preserves other Field kwargs."""
        from pydantic import BaseModel

        class TestModel(BaseModel):
            value: str = ReadOnlyField(default="default_value", description="A test field")

        schema = TestModel.model_json_schema()
        assert schema["properties"]["value"]["default"] == "default_value"
        assert schema["properties"]["value"]["description"] == "A test field"
