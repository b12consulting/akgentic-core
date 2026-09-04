"""Tests for AgentCard profile catalog functionality."""

import json
import time

import pytest

from akgentic.core import (
    ActorSystem,
    AgentCard,
    Akgent,
    BaseConfig,
    Orchestrator,
)
from akgentic.core.utils.deserializer import deserialize_object
from akgentic.core.utils.serializer import SerializableBaseModel


class TestAgentCard:
    """Test AgentCard creation and serialization."""

    def test_create_agent_card_with_config(self) -> None:
        """AgentCard can store config."""
        config = BaseConfig(name="test", role="TestAgent")
        card = AgentCard(
            skills=["testing", "validation"],
            agent_class="test.TestAgent",
            description="Test agent for profile catalog tests",
            config=config,
        )

        assert card.role == "TestAgent"
        assert "testing" in card.skills
        retrieved_config = card.get_config_copy()
        assert retrieved_config.name == "test"

    def test_create_agent_card_with_dict_config(self) -> None:
        """AgentCard accepts dict config.

        Uses ``akgentic.core.Akgent`` (itself unparameterised) so the
        config-coercion validator falls back to ``BaseConfig`` without
        attempting to import a non-existent ``test.TestAgent`` module.
        """
        card = AgentCard(
            description="A test agent",
            skills=["testing"],
            agent_class="akgentic.core.Akgent",
            config={"name": "test", "role": "TestAgent"},
        )

        config = card.get_config_copy()
        assert config.name == "test"
        assert config.role == "TestAgent"

    def test_agent_class_accepts_string(self) -> None:
        """AgentCard accepts agent_class as string."""
        card = AgentCard(
            description="Test",
            skills=["testing"],
            agent_class="test.TestAgent",
            config=BaseConfig(role="TestAgent"),
        )
        assert card.agent_class == "test.TestAgent"

    def test_agent_class_accepts_type(self) -> None:
        """AgentCard accepts agent_class as actual type."""
        card = AgentCard(
            description="Test",
            skills=["testing"],
            agent_class=Akgent,  # Using actual class type
            config=BaseConfig(role="TestAgent"),
        )
        assert card.agent_class == Akgent
        assert isinstance(card.agent_class, type)

    def test_has_skill(self) -> None:
        """AgentCard.has_skill() checks for skill presence."""
        card = AgentCard(
            description="Test",
            skills=["skill1", "skill2"],
            agent_class="test.Agent",
            config=BaseConfig(role="TestAgent"),
        )

        assert card.has_skill("skill1") is True
        assert card.has_skill("skill3") is False

    def test_metadata_extensibility(self) -> None:
        """AgentCard supports custom metadata."""
        card = AgentCard(
            description="Test",
            skills=["testing"],
            agent_class="test.Agent",
            config=BaseConfig(role="TestAgent"),
            metadata={"version": "1.0", "author": "team-alpha"},
        )

        assert card.metadata["version"] == "1.0"
        assert card.metadata["author"] == "team-alpha"

    def test_routes_to_unrestricted(self) -> None:
        """AgentCard with empty routes_to allows routing to any role."""
        card = AgentCard(
            description="Test",
            skills=["testing"],
            agent_class="test.Agent",
            config=BaseConfig(role="TestAgent"),
            routes_to=[],  # Empty = no restrictions
        )

        assert card.can_route_to("AnyRole") is True
        assert card.can_route_to("AnotherRole") is True

    def test_routes_to_restricted(self) -> None:
        """AgentCard with routes_to list restricts routing."""
        card = AgentCard(
            description="Research",
            skills=["research"],
            agent_class="test.ResearchAgent",
            config=BaseConfig(role="ResearchAgent"),
            routes_to=["WriterAgent", "AnalystAgent"],
        )

        assert card.can_route_to("WriterAgent") is True
        assert card.can_route_to("AnalystAgent") is True
        assert card.can_route_to("OtherAgent") is False

    def test_routes_to_default_empty(self) -> None:
        """AgentCard defaults to no routing restrictions."""
        card = AgentCard(
            description="Test",
            skills=["testing"],
            agent_class="test.Agent",
            config=BaseConfig(role="TestAgent"),
            # routes_to not specified - should default to []
        )

        assert card.routes_to == []
        assert card.can_route_to("AnyRole") is True

    def test_get_config_returns_independent_copies(self) -> None:
        """get_config() returns independent copies to prevent shared state."""
        card = AgentCard(
            description="Test",
            skills=["testing"],
            agent_class="test.Agent",
            config=BaseConfig(name="original", role="TestAgent"),
        )

        # Get two configs from the same card
        config1 = card.get_config_copy()
        config2 = card.get_config_copy()

        # Verify they are independent objects
        assert config1 is not config2
        assert config1 is not card.config

        # Mutate config1
        config1.name = "modified1"
        config2.name = "modified2"

        # Verify mutations are isolated
        assert config1.name == "modified1"
        assert config2.name == "modified2"
        assert card.get_config_copy().name == "original"  # Original unchanged


class TestGetAgentClass:
    """Tests for AgentCard.get_agent_class()."""

    def test_returns_type_when_agent_class_is_type(self) -> None:
        """get_agent_class() returns the class directly when already a type."""
        card = AgentCard(
            description="Test",
            skills=["testing"],
            agent_class=Akgent,
            config=BaseConfig(role="TestAgent"),
        )
        assert card.get_agent_class() is Akgent

    def test_resolves_fully_qualified_string(self) -> None:
        """get_agent_class() resolves a dotted string to the actual class."""
        card = AgentCard(
            description="Test",
            skills=["testing"],
            agent_class="akgentic.core.Akgent",
            config=BaseConfig(role="TestAgent"),
        )
        assert card.get_agent_class() is Akgent

    def test_raises_value_error_for_empty_string(self) -> None:
        """get_agent_class() raises ValueError for empty agent_class string."""
        card = AgentCard(
            description="Test",
            skills=["testing"],
            agent_class="",
            config=BaseConfig(role="TestAgent"),
        )
        with pytest.raises(ValueError, match="fully qualified dotted path"):
            card.get_agent_class()

    def test_raises_value_error_for_unqualified_name(self) -> None:
        """get_agent_class() raises ValueError for a bare class name with no dots."""
        card = AgentCard(
            description="Test",
            skills=["testing"],
            agent_class="MyAgent",
            config=BaseConfig(role="TestAgent"),
        )
        with pytest.raises(ValueError, match="fully qualified dotted path"):
            card.get_agent_class()

    def test_raises_import_error_for_missing_module(self) -> None:
        """get_agent_class() raises ImportError when the module doesn't exist."""
        card = AgentCard(
            description="Test",
            skills=["testing"],
            agent_class="nonexistent.module.SomeAgent",
            config=BaseConfig(role="TestAgent"),
        )
        with pytest.raises(ModuleNotFoundError):
            card.get_agent_class()

    def test_raises_attribute_error_for_missing_class(self) -> None:
        """get_agent_class() raises AttributeError when the class isn't in the module."""
        card = AgentCard(
            description="Test",
            skills=["testing"],
            agent_class="akgentic.core.NonExistentClass",
            config=BaseConfig(role="TestAgent"),
        )
        with pytest.raises(AttributeError):
            card.get_agent_class()


def _card(role: str, *, can_be_hired: bool | None = None) -> AgentCard:
    """Build a minimal valid AgentCard, optionally setting ``can_be_hired``.

    Omitting *can_be_hired* exercises the field default rather than an
    explicit ``False`` — the two are distinguishable and both matter.

    ``agent_class`` must be importable: these specs re-validate a dumped card,
    whose ``config`` arrives as a plain dict, and that is the path on which
    ``coerce_config_to_agent_class_generic`` resolves the class.
    """
    kwargs = {} if can_be_hired is None else {"can_be_hired": can_be_hired}
    return AgentCard(
        description=f"{role} used by the can_be_hired specs",
        skills=["testing"],
        agent_class="akgentic.core.Akgent",
        config=BaseConfig(name=role.lower(), role=role),
        **kwargs,
    )


class _CardHolder(SerializableBaseModel):
    """Wrapper proving the flag survives one level of model nesting."""

    primary: AgentCard
    others: list[AgentCard]


class TestCanBeHired:
    """``AgentCard.can_be_hired`` — default, publicness and serialization survival."""

    def test_defaults_to_false(self) -> None:
        """A card constructed without the argument is not hireable."""
        assert _card("TestAgent").can_be_hired is False

    @pytest.mark.parametrize("flag", [True, False])
    def test_explicit_value_is_honoured(self, flag: bool) -> None:
        """Both values are accepted and stored as given."""
        assert _card("TestAgent", can_be_hired=flag).can_be_hired is flag

    def test_is_a_declared_pydantic_field(self) -> None:
        """The flag is a public field, not a PrivateAttr and not a property."""
        assert "can_be_hired" in AgentCard.model_fields

    @pytest.mark.parametrize("flag", [True, False])
    def test_model_dump_contains_the_key(self, flag: bool) -> None:
        """The dumped payload carries the flag for both values."""
        dumped = _card("TestAgent", can_be_hired=flag).model_dump()
        assert dumped["can_be_hired"] is flag

    @pytest.mark.parametrize("flag", [True, False])
    def test_dump_validate_round_trip(self, flag: bool) -> None:
        """``model_dump()`` → ``model_validate()`` restores the value."""
        restored = AgentCard.model_validate(_card("TestAgent", can_be_hired=flag).model_dump())
        assert restored.can_be_hired is flag

    @pytest.mark.parametrize("flag", [True, False])
    def test_survives_nesting_in_another_serializable_model(self, flag: bool) -> None:
        """A nested card — alone and inside a list — keeps its flag through a round-trip."""
        holder = _CardHolder(
            primary=_card("PrimaryAgent", can_be_hired=flag),
            others=[
                _card("FirstOther", can_be_hired=flag),
                _card("SecondOther", can_be_hired=not flag),
            ],
        )

        restored = _CardHolder.model_validate(holder.model_dump())

        assert restored.primary.can_be_hired is flag
        assert restored.others[0].can_be_hired is flag
        assert restored.others[1].can_be_hired is (not flag)

    @pytest.mark.parametrize("flag", [True, False])
    def test_survives_the_worker_hop(self, flag: bool) -> None:
        """JSON out, JSON in, ``deserialize_object`` back — the flag is unchanged."""
        payload = _card("TestAgent", can_be_hired=flag).model_dump_json()

        restored = deserialize_object(json.loads(payload))

        assert isinstance(restored, AgentCard)
        assert restored.can_be_hired is flag

    @pytest.mark.parametrize("flag", [True, False])
    def test_survives_the_worker_hop_while_nested(self, flag: bool) -> None:
        """Nested *and* JSON — the shape the persisted record actually travels in.

        Nesting and the JSON hop are asserted separately above; the record that
        reaches a worker is both at once, and only the composition exercises the
        nested-``__model__`` rebuild on the JSON path.
        """
        holder = _CardHolder(
            primary=_card("PrimaryAgent", can_be_hired=flag),
            others=[_card("FirstOther", can_be_hired=not flag)],
        )

        restored = _CardHolder.model_validate(json.loads(holder.model_dump_json()))

        assert restored.primary.can_be_hired is flag
        assert restored.others[0].can_be_hired is (not flag)

    def test_payload_without_the_key_defaults_to_false(self) -> None:
        """A card persisted before the field existed stays loadable and is not hireable.

        The payload is dumped from a *hireable* card on purpose: dumping one that was
        already ``False`` gives the same answer whether the default was applied or the
        stored value survived, so it could not fail for the reason this spec exists.
        """
        legacy = _card("TestAgent", can_be_hired=True).model_dump()
        del legacy["can_be_hired"]

        assert AgentCard.model_validate(legacy).can_be_hired is False


class TestOrchestratorCatalog:
    """Test Orchestrator catalog management."""

    def test_register_and_retrieve_agent_profile(self) -> None:
        """Orchestrator can register and retrieve agent profiles."""
        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)

            # Register profile
            card = AgentCard(
                skills=["testing"],
                agent_class="test.TestAgent",
                description="Test agent for orchestrator profile registration",
                config=BaseConfig(name="test", role="TestAgent"),
            )
            orch_proxy.register_agent_profile(card)

            # Retrieve by role
            retrieved = orch_proxy.get_agent_profile("TestAgent")
            assert retrieved is not None
            assert retrieved.role == "TestAgent"
        finally:
            system.shutdown()

    def test_get_agent_catalog(self) -> None:
        """Orchestrator returns all registered profiles."""
        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)

            # Register multiple profiles
            orch_proxy.register_agent_profile(
                AgentCard(
                    description="First agent",
                    skills=["skill1"],
                    agent_class="test.Agent1",
                    config=BaseConfig(role="Agent1"),
                )
            )
            orch_proxy.register_agent_profile(
                AgentCard(
                    description="Second agent",
                    skills=["skill2"],
                    agent_class="test.Agent2",
                    config=BaseConfig(role="Agent2"),
                )
            )

            catalog = orch_proxy.get_agent_catalog()
            assert len(catalog) == 2
            roles = [card.role for card in catalog]
            assert "Agent1" in roles
            assert "Agent2" in roles
        finally:
            system.shutdown()

    def test_get_profiles_by_skill(self) -> None:
        """Orchestrator can filter profiles by skill."""
        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)

            # Register profiles with different skills
            orch_proxy.register_agent_profile(
                AgentCard(
                    description="Research",
                    skills=["web_search", "pdf_extraction"],
                    agent_class="test.ResearchAgent",
                    config=BaseConfig(role="ResearchAgent"),
                )
            )
            orch_proxy.register_agent_profile(
                AgentCard(
                    description="Writer",
                    skills=["writing", "summarization"],
                    agent_class="test.WriterAgent",
                    config=BaseConfig(role="WriterAgent"),
                )
            )
            orch_proxy.register_agent_profile(
                AgentCard(
                    description="Analyst",
                    skills=["web_search", "analysis"],
                    agent_class="test.AnalystAgent",
                    config=BaseConfig(role="AnalystAgent"),
                )
            )

            # Find agents with web_search skill
            web_searchers = orch_proxy.get_profiles_by_skill("web_search")
            assert len(web_searchers) == 2
            roles = [card.role for card in web_searchers]
            assert "ResearchAgent" in roles
            assert "AnalystAgent" in roles
            assert "WriterAgent" not in roles
        finally:
            system.shutdown()

    def test_get_available_roles(self) -> None:
        """Orchestrator returns list of available roles."""
        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)

            orch_proxy.register_agent_profile(
                AgentCard(
                    description="A1",
                    skills=[],
                    agent_class="test.A1",
                    config=BaseConfig(role="Agent1"),
                )
            )
            orch_proxy.register_agent_profile(
                AgentCard(
                    description="A2",
                    skills=[],
                    agent_class="test.A2",
                    config=BaseConfig(role="Agent2"),
                )
            )

            roles = orch_proxy.get_available_roles()
            assert "Agent1" in roles
            assert "Agent2" in roles
        finally:
            system.shutdown()

    def test_get_available_skills(self) -> None:
        """Orchestrator returns unique list of all skills."""
        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)

            orch_proxy.register_agent_profile(
                AgentCard(
                    description="A1",
                    skills=["skill1", "skill2"],
                    agent_class="test.A1",
                    config=BaseConfig(role="Agent1"),
                )
            )
            orch_proxy.register_agent_profile(
                AgentCard(
                    description="A2",
                    skills=["skill2", "skill3"],
                    agent_class="test.A2",
                    config=BaseConfig(role="Agent2"),
                )
            )

            skills = orch_proxy.get_available_skills()
            # Should be sorted and unique
            assert skills == ["skill1", "skill2", "skill3"]
        finally:
            system.shutdown()


class SimpleAgent(Akgent):
    """Simple test agent for discovery tests."""

    pass


class TestAgentDiscovery:
    """Test agent-side discovery methods."""

    def test_discover_catalog_from_agent(self) -> None:
        """Agent can discover catalog via orchestrator."""
        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            # Register profiles
            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)
            orch_proxy.register_agent_profile(
                AgentCard(
                    description="Test",
                    skills=["testing"],
                    agent_class="test.TestAgent",
                    config=BaseConfig(role="TestAgent"),
                )
            )

            # Create agent via orchestrator (propagates orchestrator reference)
            agent_addr = orch_proxy.createActor(
                SimpleAgent, config=BaseConfig(name="simple", role="SimpleAgent")
            )

            time.sleep(0.1)

            # Agent discovers catalog
            agent_proxy = system.proxy_ask(agent_addr, SimpleAgent)
            catalog = agent_proxy.discover_catalog()

            assert len(catalog) == 1
            assert catalog[0].role == "TestAgent"
        finally:
            system.shutdown()

    def test_discover_profile_by_role(self) -> None:
        """Agent can discover specific profile by role."""
        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)
            orch_proxy.register_agent_profile(
                AgentCard(
                    description="Research",
                    skills=["web_search"],
                    agent_class="test.ResearchAgent",
                    config=BaseConfig(role="ResearchAgent"),
                )
            )

            agent_addr = orch_proxy.createActor(
                SimpleAgent, config=BaseConfig(name="simple", role="SimpleAgent")
            )

            time.sleep(0.1)

            agent_proxy = system.proxy_ask(agent_addr, SimpleAgent)
            profile = agent_proxy.get_agent_card("ResearchAgent")

            assert profile is not None
            assert profile.role == "ResearchAgent"
            assert "web_search" in profile.skills
        finally:
            system.shutdown()

    def test_find_agents_with_skill(self) -> None:
        """Agent can find profiles by skill."""
        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)
            orch_proxy.register_agent_profile(
                AgentCard(
                    description="A1",
                    skills=["skill1", "skill2"],
                    agent_class="test.A1",
                    config=BaseConfig(role="Agent1"),
                )
            )
            orch_proxy.register_agent_profile(
                AgentCard(
                    description="A2",
                    skills=["skill2", "skill3"],
                    agent_class="test.A2",
                    config=BaseConfig(role="Agent2"),
                )
            )

            agent_addr = orch_proxy.createActor(
                SimpleAgent, config=BaseConfig(name="simple", role="SimpleAgent")
            )

            time.sleep(0.1)

            agent_proxy = system.proxy_ask(agent_addr, SimpleAgent)
            matches = agent_proxy.find_agents_with_skill("skill2")

            assert len(matches) == 2
            roles = [card.role for card in matches]
            assert "Agent1" in roles
            assert "Agent2" in roles
        finally:
            system.shutdown()

    def test_discovery_without_orchestrator(self) -> None:
        """Discovery methods return empty when no orchestrator."""
        system = ActorSystem()
        try:
            # Create agent WITHOUT orchestrator
            agent_addr = system.createActor(
                SimpleAgent, config=BaseConfig(name="simple", role="SimpleAgent")
            )

            agent_proxy = system.proxy_ask(agent_addr, SimpleAgent)

            # Should return empty results
            catalog = agent_proxy.discover_catalog()
            assert catalog == []

            profile = agent_proxy.get_agent_card("SomeAgent")
            assert profile is None

            matches = agent_proxy.find_agents_with_skill("some_skill")
            assert matches == []

            roles = agent_proxy.get_available_roles()
            assert roles == []
        finally:
            system.shutdown()

    def test_get_available_roles_from_agent(self) -> None:
        """Agent can get list of available roles from catalog."""
        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)
            orch_proxy.register_agent_profile(
                AgentCard(
                    description="Research",
                    skills=["web_search"],
                    agent_class="test.ResearchAgent",
                    config=BaseConfig(role="ResearchAgent"),
                )
            )
            orch_proxy.register_agent_profile(
                AgentCard(
                    description="Writer",
                    skills=["writing"],
                    agent_class="test.WriterAgent",
                    config=BaseConfig(role="WriterAgent"),
                )
            )

            agent_addr = orch_proxy.createActor(
                SimpleAgent, config=BaseConfig(name="simple", role="SimpleAgent")
            )

            time.sleep(0.1)

            agent_proxy = system.proxy_ask(agent_addr, SimpleAgent)
            roles = agent_proxy.get_available_roles()

            assert len(roles) == 2
            assert "ResearchAgent" in roles
            assert "WriterAgent" in roles
        finally:
            system.shutdown()
