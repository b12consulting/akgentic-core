"""Tests for Story 9.2: ``AgentCard.role`` is a derived property of ``config.role``.

Covers acceptance criteria #1–#11 from
``_bmad-output/akgentic-core/stories/9-2-agentcard-role-derives-from-config-role.md``.
"""

from __future__ import annotations

import warnings

import pytest
from pydantic import ValidationError

import akgentic.core.agent_card as agent_card_module
from akgentic.core import ActorSystem, AgentCard, BaseConfig, Orchestrator


@pytest.fixture(autouse=True)
def _reset_deprecation_flag() -> None:
    """Reset the once-per-process deprecation flag before each test.

    The production flag is module-level by design (Story 9.2 Dev Notes) — for
    tests we must reset it between cases to make ``DeprecationWarning``
    emission observable and deterministic.
    """
    agent_card_module._ROLE_DEPRECATION_WARNED = False
    yield
    agent_card_module._ROLE_DEPRECATION_WARNED = False


class TestRoleIsDerivedProperty:
    """AC #1, #2: role is no longer a field, but ``card.role`` still works."""

    def test_role_not_in_model_fields(self) -> None:
        """AC #1: ``role`` does not appear in ``AgentCard.model_fields``."""
        assert "role" not in AgentCard.model_fields

    def test_role_property_returns_config_role(self) -> None:
        """AC #2: ``card.role`` returns ``card.config.role``."""
        card = AgentCard(
            description="Manager",
            skills=[],
            agent_class="akgentic.core.Akgent",
            config=BaseConfig(name="mgr", role="Manager"),
        )
        assert card.role == "Manager"
        assert card.role == card.config.role


class TestLegacyRoleHoist:
    """AC #3, #6, #7: legacy top-level ``role=`` is accepted and hoisted."""

    def test_legacy_role_hoisted_when_config_role_empty(self) -> None:
        """AC #3: legacy ``role="X"`` with empty ``config.role`` is hoisted."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            card = AgentCard(
                role="Manager",
                description="Manager",
                skills=[],
                agent_class="akgentic.core.Akgent",
                config=BaseConfig(role=""),
            )
        assert card.config.role == "Manager"
        assert card.role == "Manager"
        assert any(issubclass(w.category, DeprecationWarning) for w in caught)

    def test_yaml_payload_without_top_level_role_validates(self) -> None:
        """AC #6: payload without top-level ``role:`` validates cleanly."""
        payload = {
            "description": "Manager",
            "skills": [],
            "agent_class": "akgentic.core.Akgent",
            "config": {"name": "mgr", "role": "Manager"},
        }
        card = AgentCard.model_validate(payload)
        assert card.role == "Manager"

    def test_agreeing_legacy_role_is_silent(self) -> None:
        """AC #7: legacy ``role="X"`` matching ``config.role`` emits no warning."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            card = AgentCard(
                role="Manager",
                description="Manager",
                skills=[],
                agent_class="akgentic.core.Akgent",
                config=BaseConfig(role="Manager"),
            )
        assert card.config.role == "Manager"
        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert dep_warnings == []


class TestDisagreementIsError:
    """AC #4: disagreement between legacy ``role=`` and ``config.role`` raises."""

    def test_disagreement_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AgentCard(
                role="Manager",
                description="Manager",
                skills=[],
                agent_class="akgentic.core.Akgent",
                config=BaseConfig(role="Supervisor"),
            )
        msg = str(exc_info.value)
        assert "Manager" in msg
        assert "Supervisor" in msg
        assert "config.role" in msg


class TestEmptyConfigRoleIsError:
    """AC #5: empty ``config.role`` after hoisting is a validation error."""

    def test_empty_config_role_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AgentCard(
                description="Nameless",
                skills=[],
                agent_class="akgentic.core.Akgent",
                config=BaseConfig(role=""),
            )
        assert "config.role" in str(exc_info.value)


class TestModelDumpOmitsTopLevelRole:
    """AC #9: ``model_dump()`` does not emit a top-level ``role`` key."""

    def test_model_dump_no_top_level_role(self) -> None:
        card = AgentCard(
            description="Manager",
            skills=[],
            agent_class="akgentic.core.Akgent",
            config=BaseConfig(name="mgr", role="Manager"),
        )
        dumped = card.model_dump()
        assert "role" not in dumped
        # Role still reachable via config
        assert dumped["config"]["role"] == "Manager"


class TestRoundTripStability:
    """AC #10: dump → validate round-trips are idempotent."""

    def _base_card(self) -> AgentCard:
        return AgentCard(
            description="Manager",
            skills=["coordination"],
            agent_class="akgentic.core.Akgent",
            config=BaseConfig(name="mgr", role="Manager"),
            routes_to=["Worker"],
        )

    def test_round_trip_preserves_card(self) -> None:
        original = self._base_card()
        round1 = AgentCard.model_validate(original.model_dump())
        round2 = AgentCard.model_validate(round1.model_dump())
        assert round1.role == original.role == "Manager"
        assert round2.role == original.role
        assert round1.config.role == original.config.role
        assert round1.skills == original.skills
        assert round2.model_dump() == round1.model_dump()

    def test_legacy_payload_round_trip(self) -> None:
        """AC #7 + #10: legacy payload with top-level role still round-trips."""
        legacy_payload = {
            "role": "Manager",
            "description": "Manager",
            "skills": [],
            "agent_class": "akgentic.core.Akgent",
            "config": {"name": "mgr", "role": "Manager"},
        }
        card = AgentCard.model_validate(legacy_payload)
        dumped = card.model_dump()
        assert "role" not in dumped
        re_validated = AgentCard.model_validate(dumped)
        assert re_validated.role == "Manager"


class TestDeprecationWarningOncePerProcess:
    """AC #3 + Dev Note: at most one ``DeprecationWarning`` across many legacy loads."""

    def test_single_warning_across_many_legacy_validations(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for _ in range(10):
                AgentCard(
                    role="Manager",
                    description="Manager",
                    skills=[],
                    agent_class="akgentic.core.Akgent",
                    config=BaseConfig(role=""),
                )
        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) == 1


class TestOrchestratorRegistryKey:
    """AC #8: Orchestrator registers by ``card.config.role`` (via the property)."""

    def test_registry_key_is_config_role(self) -> None:
        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )
            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)

            card_a = AgentCard(
                description="A",
                skills=[],
                agent_class="akgentic.core.Akgent",
                config=BaseConfig(name="a", role="AgentA"),
            )
            card_b = AgentCard(
                description="B",
                skills=[],
                agent_class="akgentic.core.Akgent",
                config=BaseConfig(name="b", role="AgentB"),
            )
            orch_proxy.register_agent_profile(card_a)
            orch_proxy.register_agent_profile(card_b)

            # Lookup by the config.role string returns the right card.
            got_a = orch_proxy.get_agent_profile("AgentA")
            got_b = orch_proxy.get_agent_profile("AgentB")
            assert got_a is not None and got_a.config.role == "AgentA"
            assert got_b is not None and got_b.config.role == "AgentB"
        finally:
            system.shutdown()


# AC #11 (agent YAML fixtures drop top-level `role:`) is intentionally NOT
# asserted in this test module. Those fixtures live in the PARENT repo
# (``data/catalog/agent-team-v1/agent/*.yaml``) — outside the ``akgentic-core``
# submodule boundary. A submodule test that reads parent-repo files would
# silently ``pytest.skip`` in standalone CI (where the submodule is checked
# out on its own) and would violate CLAUDE.md Golden Rule #4. The backward-
# compatible hoist path exercised by ``TestLegacyRoleHoist`` above is what
# keeps the legacy YAML shape working; fixture migration is verified by the
# parent-repo catalog load in integration tests.
