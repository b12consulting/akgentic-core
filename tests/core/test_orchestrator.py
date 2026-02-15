"""Tests for Orchestrator agent."""

import uuid
from collections.abc import Generator

import pykka
import pytest

from akgentic.actor_system_impl import ActorSystemImpl
from akgentic.agent import Akgent
from akgentic.agent_config import BaseConfig
from akgentic.agent_state import BaseState
from akgentic.messages.message import UserMessage
from akgentic.orchestrator import Orchestrator, OrchestratorEventSubscriber


@pytest.fixture(autouse=True)
def cleanup_actors() -> Generator[None, None, None]:
    """Ensure all actors are stopped after each test."""
    yield
    pykka.ActorRegistry.stop_all()


class MockEventSubscriber:
    """Test event subscriber for verifying notification pattern."""

    def __init__(self):
        """Initialize event tracking."""
        self.events: list[str] = []

    def on_agent_started(self, msg):  # type: ignore
        """Track agent started events."""
        self.events.append("agent_started")

    def on_agent_stopped(self, msg):  # type: ignore
        """Track agent stopped events."""
        self.events.append("agent_stopped")

    def on_state_changed(self, msg):  # type: ignore
        """Track state changed events."""
        self.events.append("state_changed")

    def on_message_sent(self, msg):  # type: ignore
        """Track message sent events."""
        self.events.append("message_sent")

    def on_message_received(self, msg):  # type: ignore
        """Track message received events."""
        self.events.append("message_received")

    def on_message_processed(self, msg):  # type: ignore
        """Track message processed events."""
        self.events.append("message_processed")

    def on_error(self, msg):  # type: ignore
        """Track error events."""
        self.events.append("error")


class FailingSubscriber:
    """Subscriber that raises exceptions to test fault tolerance."""

    def on_agent_started(self, msg):  # type: ignore
        """Always raise exception."""
        raise RuntimeError("Subscriber failure")

    def on_agent_stopped(self, msg):  # type: ignore
        """Always raise exception."""
        raise RuntimeError("Subscriber failure")

    def on_state_changed(self, msg):  # type: ignore
        """Always raise exception."""
        raise RuntimeError("Subscriber failure")

    def on_message_sent(self, msg):  # type: ignore
        """Always raise exception."""
        raise RuntimeError("Subscriber failure")

    def on_message_received(self, msg):  # type: ignore
        """Always raise exception."""
        raise RuntimeError("Subscriber failure")

    def on_message_processed(self, msg):  # type: ignore
        """Always raise exception."""
        raise RuntimeError("Subscriber failure")

    def on_error(self, msg):  # type: ignore
        """Always raise exception."""
        raise RuntimeError("Subscriber failure")


class SimpleAgent(Akgent[BaseConfig, BaseState]):
    """Simple agent for testing orchestrator interaction."""

    def receiveMsg_str(self, msg: str, sender):  # type: ignore
        """Handle string messages."""
        return f"received: {msg}"


class TestOrchestratorInitialization:
    """Tests for Orchestrator initialization."""

    def test_orchestrator_initializes_with_empty_state(self) -> None:
        """Test that orchestrator initializes with its own StartMessage."""
        from akgentic.messages.orchestrator import StartMessage

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
        assert orch.get_llm_context().get() == {}
        assert orch.get_tool_state().get() == {}
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
        from akgentic.messages.orchestrator import StartMessage

        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        # Initially contains orchestrator's own StartMessage
        messages = orch.get_messages().get()
        assert len(messages) == 1
        assert isinstance(messages[0], StartMessage)

        orch_ref.stop()

    def test_get_llm_context(self) -> None:
        """Test get_llm_context returns llm_context_dict."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        # Initially empty
        context = orch.get_llm_context().get()
        assert context == {}

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

    def test_get_tool_state_all(self) -> None:
        """Test get_tool_state returns all tool states when no filter."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        # Initially empty
        tool_states = orch.get_tool_state().get()
        assert tool_states == {}

        orch_ref.stop()

    def test_get_tool_state_specific_tool(self) -> None:
        """Test get_tool_state returns empty dict for non-existent tool."""
        config = BaseConfig(name="test-orchestrator", role="Orchestrator")
        orch_ref = Orchestrator.start(config=config)
        orch = orch_ref.proxy()

        tool_state = orch.get_tool_state("non-existent").get()
        assert tool_state == {}

        orch_ref.stop()


class TestZeroDependencies:
    """Tests verifying zero external dependencies."""

    def test_no_redis_imports(self) -> None:
        """Test that orchestrator module has no Redis imports."""
        import akgentic.orchestrator as orch_module

        # Check module-level imports
        module_globals = vars(orch_module)
        assert "redis" not in module_globals
        assert "aioredis" not in module_globals

    def test_orchestrator_works_without_redis(self) -> None:
        """Test orchestrator functions without Redis."""
        from akgentic.messages.orchestrator import StartMessage

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
        """Test orchestrator integrates with ActorSystemImpl."""
        # Create actor system
        system = ActorSystemImpl()

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
        from akgentic.messages.orchestrator import StartMessage

        # This test verifies orchestrator can be created and used without Redis/DB
        system = ActorSystemImpl()

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
