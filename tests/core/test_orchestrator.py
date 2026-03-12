"""Tests for Orchestrator agent."""

from collections.abc import Generator
from typing import Never

import pykka
import pytest

from akgentic.core.actor_system_impl import ActorSystem
from akgentic.core.agent import Akgent
from akgentic.core.agent_config import BaseConfig
from akgentic.core.agent_state import BaseState
from akgentic.core.orchestrator import Orchestrator


@pytest.fixture(autouse=True)
def cleanup_actors() -> Generator[None, None, None]:
    """Ensure all actors are stopped after each test."""
    yield
    pykka.ActorRegistry.stop_all()


class MockEventSubscriber:
    """Test event subscriber for verifying notification pattern."""

    def __init__(self) -> None:
        """Initialize event tracking."""
        self.events: list[str] = []

    def on_agent_started(self) -> None:
        self.events.append("agent_started")

    def on_agent_stopped(self) -> None:
        """Track agent stopped events."""
        self.events.append("agent_stopped")

    def on_state_changed(self) -> None:
        self.events.append("state_changed")

    def on_message_sent(self) -> None:
        self.events.append("message_sent")

    def on_message_received(
        self,
    ) -> None:
        """Track message received events."""
        self.events.append("message_received")

    def on_message_processed(self) -> None:
        """Track message processed events."""
        self.events.append("message_processed")

    def on_error(self) -> None:
        """Track error events."""
        self.events.append("error")


class FailingSubscriber:
    """Subscriber that raises exceptions to test fault tolerance."""

    def on_agent_started(self) -> Never:
        """Always raise exception."""
        raise RuntimeError("Subscriber failure")

    def on_agent_stopped(self) -> Never:
        """Always raise exception."""
        raise RuntimeError("Subscriber failure")

    def on_state_changed(self) -> Never:
        """Always raise exception."""
        raise RuntimeError("Subscriber failure")

    def on_message_sent(self) -> Never:
        raise RuntimeError("Subscriber failure")

    def on_message_received(self) -> Never:
        raise RuntimeError("Subscriber failure")

    def on_message_processed(self) -> Never:
        """Always raise exception."""
        raise RuntimeError("Subscriber failure")

    def on_error(self) -> Never:
        """Always raise exception."""
        raise RuntimeError("Subscriber failure")


class SimpleAgent(Akgent[BaseConfig, BaseState]):
    """Simple agent for testing orchestrator interaction."""

    def receiveMsg_str(self, msg: str) -> str:
        """Handle string messages."""
        return f"received: {msg}"


class TestOrchestratorInitialization:
    """Tests for Orchestrator initialization."""

    def test_orchestrator_initializes_with_empty_state(self) -> None:
        """Test that orchestrator initializes with its own StartMessage."""
        from akgentic.core.messages.orchestrator import StartMessage

        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        # Verify initialization - orchestrator sends its own StartMessage
        messages = orch.get_messages().get()
        assert len(messages) == 1
        assert isinstance(messages[0], StartMessage)
        assert messages[0].config.name == "test-orchestrator"

        # Other collections remain empty
        assert orch.get_states().get() == {}
        assert orch.get_team().get() == []  # Orchestrator excluded from team

        orch_ref.stop()


class TestTeamManagement:
    """Tests for team management methods."""

    def test_get_team_empty_initially(self) -> None:
        """Test get_team returns empty list initially."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        team = orch.get_team().get()
        assert team == []

        orch_ref.stop()

    def test_get_team_member_not_found(self) -> None:
        """Test get_team_member returns None for non-existent agent."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        found = orch.get_team_member("non-existent").get()
        assert found is None

        orch_ref.stop()


class TestQueryMethods:
    """Tests for query methods."""

    def test_get_messages_all(self) -> None:
        """Test get_messages returns all messages when no filter."""
        from akgentic.core.messages.orchestrator import StartMessage

        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        # Initially contains orchestrator's own StartMessage
        messages = orch.get_messages().get()
        assert len(messages) == 1
        assert isinstance(messages[0], StartMessage)

        orch_ref.stop()

    def test_get_states(self) -> None:
        """Test get_states returns state_dict."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        # Initially empty
        states = orch.get_states().get()
        assert states == {}

        orch_ref.stop()


class TestZeroDependencies:
    """Tests verifying zero external dependencies."""

    def test_no_redis_imports(self) -> None:
        """Test that orchestrator module has no Redis imports."""
        import akgentic.core.orchestrator as orch_module

        # Check module-level imports
        module_globals = vars(orch_module)
        assert "redis" not in module_globals
        assert "aioredis" not in module_globals

    def test_orchestrator_works_without_redis(self) -> None:
        """Test orchestrator functions without Redis."""
        from akgentic.core.messages.orchestrator import StartMessage

        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        # Perform basic operations
        team = orch.get_team().get()
        assert team == []

        # Orchestrator records its own StartMessage
        messages = orch.get_messages().get()
        assert len(messages) == 1
        assert isinstance(messages[0], StartMessage)

        orch_ref.stop()


class TestIntegration:
    """Integration tests for Orchestrator with real agent system."""

    def test_orchestrator_integration_with_actor_system(self) -> None:
        """Test orchestrator integrates with ActorSystem."""
        # Create actor system
        system = ActorSystem()

        # Create orchestrator - should integrate without errors
        orch_config = BaseConfig(name="orchestrator", role="Orchestrator")
        orch_addr = system.createActor(Orchestrator, config=orch_config)

        # Verify orchestrator is alive
        assert orch_addr.is_alive()

        # Verify basic functionality
        orch_proxy = orch_addr._actor_ref.proxy()  # type: ignore
        team = orch_proxy.get_team().get()
        assert isinstance(team, list)

        # Cleanup
        system.shutdown()

    def test_zero_infrastructure_requirements(self) -> None:
        """Test that orchestrator requires no external infrastructure."""
        from akgentic.core.messages.orchestrator import StartMessage

        # This test verifies orchestrator can be created and used without Redis/DB
        system = ActorSystem()

        # Create orchestrator - should not throw any connection errors
        orch_config = BaseConfig(name="orchestrator", role="Orchestrator")
        orch_addr = system.createActor(Orchestrator, config=orch_config)

        # Verify basic functionality
        orch_proxy = orch_addr._actor_ref.proxy()  # type: ignore
        messages = orch_proxy.get_messages().get()
        # Orchestrator records its own StartMessage
        assert len(messages) == 1
        assert isinstance(messages[0], StartMessage)

        system.shutdown()
