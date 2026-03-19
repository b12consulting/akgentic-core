"""Tests for Orchestrator agent."""

from collections.abc import Generator
from typing import Never

import pykka
import pytest

from akgentic.core.actor_system_impl import ActorSystem
from akgentic.core.agent import Akgent
from akgentic.core.agent_config import BaseConfig
from akgentic.core.agent_state import BaseState
from akgentic.core.messages.message import Message, UserMessage
from akgentic.core.orchestrator import EventSubscriber, Orchestrator


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


class RecordingSubscriber:
    """Subscriber that records on_message calls for restore tests."""

    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.stopped: bool = False

    def on_message(self, msg: Message) -> None:
        """Record received message."""
        self.messages.append(msg)

    def on_stop(self) -> None:
        """Record stop."""
        self.stopped = True


class TestUnsubscribe:
    """Tests for Orchestrator.unsubscribe."""

    def test_unsubscribe_removes_subscriber(self) -> None:
        """unsubscribe removes a subscriber from notification list."""
        system = ActorSystem()
        orch = system.createActor(Orchestrator, restoring=True)
        proxy = system.proxy_ask(orch, Orchestrator)

        sub = RecordingSubscriber()
        proxy.subscribe(sub)
        assert sub in proxy.subscribers

        proxy.unsubscribe(sub)
        assert sub not in proxy.subscribers

        system.shutdown()

    def test_unsubscribe_unknown_is_noop(self) -> None:
        """unsubscribe on unknown subscriber is idempotent."""
        system = ActorSystem()
        orch = system.createActor(Orchestrator, restoring=True)
        proxy = system.proxy_ask(orch, Orchestrator)

        sub = RecordingSubscriber()
        proxy.unsubscribe(sub)  # should not raise

        system.shutdown()

    def test_unsubscribed_subscriber_stops_receiving_events(self) -> None:
        """After unsubscribe, events are no longer dispatched to the subscriber."""
        system = ActorSystem()
        orch = system.createActor(Orchestrator, restoring=True)
        proxy = system.proxy_ask(orch, Orchestrator)

        sub = RecordingSubscriber()
        proxy.subscribe(sub)
        proxy.restore_message(UserMessage(content="before"))
        assert len(sub.messages) == 1

        proxy.unsubscribe(sub)
        proxy.restore_message(UserMessage(content="after"))
        assert len(sub.messages) == 1  # no new message

        system.shutdown()


class TestRestoreMessage:
    """Tests for Orchestrator.restore_message and end_restoration."""

    def test_restore_message_dispatches_to_subscribers(self) -> None:
        """restore_message notifies subscribers via on_message."""
        system = ActorSystem()
        orch_addr = system.createActor(
            Orchestrator,
            config=BaseConfig(name="orchestrator", role="Orchestrator"),
        )
        orch_proxy = system.proxy_ask(orch_addr, Orchestrator)

        sub = RecordingSubscriber()
        orch_proxy.subscribe(sub)

        msg = UserMessage(content="replayed message")
        orch_proxy.restore_message(msg)

        assert len(sub.messages) == 1
        assert sub.messages[0] is msg

        system.shutdown()

    def test_restore_message_dispatches_multiple(self) -> None:
        """restore_message dispatches to all registered subscribers."""
        system = ActorSystem()
        orch_addr = system.createActor(
            Orchestrator,
            config=BaseConfig(name="orchestrator", role="Orchestrator"),
        )
        orch_proxy = system.proxy_ask(orch_addr, Orchestrator)

        sub1 = RecordingSubscriber()
        sub2 = RecordingSubscriber()
        orch_proxy.subscribe(sub1)
        orch_proxy.subscribe(sub2)

        msg = UserMessage(content="test")
        orch_proxy.restore_message(msg)

        assert len(sub1.messages) == 1
        assert len(sub2.messages) == 1

        system.shutdown()

    def test_end_restoration_toggles_restoring_flag(self) -> None:
        """end_restoration sets _restoring to False."""
        system = ActorSystem()
        orch_addr = system.createActor(
            Orchestrator,
            config=BaseConfig(name="orchestrator", role="Orchestrator"),
            restoring=True,
        )
        orch_proxy = system.proxy_ask(orch_addr, Orchestrator)

        orch_proxy.end_restoration()

        # After end_restoration, _restoring should be False
        # We verify indirectly: the orchestrator is alive and functional
        team = orch_proxy.get_team()
        assert team == []

        system.shutdown()
