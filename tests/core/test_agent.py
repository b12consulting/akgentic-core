"""Tests for Akgent base class and message dispatch.

Tests cover:
- Agent initialization and lifecycle
- Message dispatch with receiveMsg_<Type> pattern
- SUPER sentinel fallthrough behavior
- Child actor creation with context propagation
- State management with observer pattern
- Proxy helpers (tell/ask modes)
- Telemetry integration (orchestrator notifications)
"""

import logging
import uuid
from collections.abc import Iterator
from typing import Any, cast
from unittest.mock import MagicMock

import pykka
import pytest
from pydantic import PrivateAttr

from akgentic.core.actor_address import ActorAddress
from akgentic.core.actor_address_impl import ActorAddressImpl
from akgentic.core.agent import Akgent, ProxyWrapper, WarningError
from akgentic.core.agent_config import BaseConfig
from akgentic.core.agent_state import BaseState
from akgentic.core.messages.message import Message, StopRecursively
from akgentic.core.messages.orchestrator import (
    ErrorMessage,
    EventMessage,
    ProcessedMessage,
    ReceivedMessage,
    StateChangedMessage,
    StopMessage,
    WarningMessage,
)
from akgentic.core.orchestrator import Orchestrator


class SampleMessage(Message):
    """Test message for dispatch testing."""

    content: str = ""


class DerivedSampleMessage(SampleMessage):
    """Derived test message for MRO testing."""

    extra: str = ""


class SampleAgent(Akgent[BaseConfig, BaseState]):
    """Test agent with message handler."""

    def __init__(self, **kwargs) -> None:
        self.received_messages: list = []
        super().__init__(**kwargs)

    def receiveMsg_SampleMessage(self, msg: SampleMessage, sender: Any):
        """Handle SampleMessage and derived types."""
        self.received_messages.append(msg)
        return msg.content


class SuperSampleAgent(Akgent[BaseConfig, BaseState]):
    """Test agent that uses SUPER sentinel."""

    def __init__(self, **kwargs) -> None:
        self.handled_at_base = False
        super().__init__(**kwargs)

    def receiveMsg_SampleMessage(self, msg: SampleMessage, sender: Any):
        """Decline to handle - return SUPER."""
        return self.SUPER

    def receiveMsg_Message(self, msg: Message, sender: Any) -> str:
        """Base Message handler - catches fallthrough."""
        self.handled_at_base = True
        return "base_handler"


@pytest.fixture
def agent_setup():
    """Create agent with required context."""
    agent_id = uuid.uuid4()
    team_id = uuid.uuid4()
    config = BaseConfig(name="test-agent", role="Tester")
    return agent_id, config, team_id


@pytest.fixture(autouse=True)
def cleanup_actors():
    """Ensure all actors stopped after each test."""
    yield
    try:
        pykka.ActorRegistry.stop_all()
    except Exception:
        pass


class TestAgentInitialization:
    """Tests for agent lifecycle."""

    def test_agent_starts_and_stops(self, agent_setup) -> None:
        """Agent can be started and stopped cleanly."""
        agent_id, config, team_id = agent_setup
        ref = SampleAgent.start(
            agent_id=agent_id,
            config=config,
            team_id=team_id,
        )
        try:
            assert ref.is_alive()
            address = ActorAddressImpl(ref)
            assert address.agent_id == agent_id
        finally:
            ref.stop()

    def test_agent_keyword_arg_initialization(self) -> None:
        """Agent can be initialized with explicit keyword arguments."""
        agent_id = uuid.uuid4()
        team_id = uuid.uuid4()
        user_id = uuid.uuid4()
        config = BaseConfig(name="test-agent", role="Tester")

        ref = SampleAgent.start(
            agent_id=agent_id,
            config=config,
            user_id=user_id,
            user_email="test@example.com",
            team_id=team_id,
            parent=None,
            orchestrator=None,
        )
        try:
            assert ref.is_alive()
            agent_agent_id = ref.proxy().agent_id.get()
            agent_config_name = ref.proxy().config.get().name

            assert agent_agent_id == agent_id
            assert agent_config_name == "test-agent"

            # Verify child creation propagates context correctly
            child_config = BaseConfig(name="child")
            child_address = (
                ref.proxy().createActor(SampleAgent, uuid.uuid4(), child_config).get(timeout=5)
            )
            assert child_address.is_alive()
        finally:
            ref.stop()

    def test_agent_keyword_args_with_defaults(self) -> None:
        """Agent keyword args use defaults when not specified."""
        config = BaseConfig(name="test-agent")

        ref = SampleAgent.start(config=config)
        try:
            assert ref.is_alive()
            agent_agent_id = ref.proxy().agent_id.get()
            agent_config = ref.proxy().config.get()

            # agent_id defaults to uuid4()
            assert agent_agent_id is not None
            assert isinstance(agent_agent_id, uuid.UUID)

            # config is set
            assert agent_config.name == "test-agent"
        finally:
            ref.stop()

    def test_agent_receives_uuid_and_config(self, agent_setup) -> None:
        """Agent initialization extracts args correctly."""
        agent_id, config, team_id = agent_setup
        ref = SampleAgent.start(
            agent_id=agent_id,
            config=config,
            team_id=team_id,
        )
        try:
            # Access via proxy to get agent attributes
            agent_config_name = ref.proxy().config.get().name
            agent_agent_id = ref.proxy().agent_id.get()

            assert agent_config_name == "test-agent"
            assert agent_agent_id == agent_id
        finally:
            ref.stop()

    def test_agent_defaults_name_and_role(self, agent_setup) -> None:
        """Agent sets default name and role if not provided."""
        agent_id, _, team_id = agent_setup
        config = BaseConfig()  # No name or role
        ref = SampleAgent.start(
            agent_id=agent_id,
            config=config,
            team_id=team_id,
        )
        try:
            agent_config_name = ref.proxy().config.get().name
            agent_config_role = ref.proxy().config.get().role

            # Name defaults to actor ref string
            assert agent_config_name is not None
            assert len(agent_config_name) > 0

            # Role defaults to class name
            assert agent_config_role == "SampleAgent"
        finally:
            ref.stop()

    def test_team_id_auto_generated_when_not_provided(self) -> None:
        """Actor started without team_id gets a valid uuid.UUID auto-generated."""
        config = BaseConfig(name="no-team-agent")
        ref = SampleAgent.start(config=config)
        try:
            address = ActorAddressImpl(ref)
            team_id = address.team_id
            assert isinstance(team_id, uuid.UUID)
        finally:
            ref.stop()

    def test_team_id_explicit_value_preserved(self) -> None:
        """Actor started with an explicit team_id stores that exact value."""
        expected_team_id = uuid.uuid4()
        config = BaseConfig(name="explicit-team-agent")
        ref = SampleAgent.start(config=config, team_id=expected_team_id)
        try:
            address = ActorAddressImpl(ref)
            assert address.team_id == expected_team_id
        finally:
            ref.stop()

    def test_init_hook_called(self, agent_setup) -> None:
        """Agent on_start() hook is called during initialization."""

        class InitTestAgent(Akgent[BaseConfig, BaseState]):
            def __init__(self, **kwargs) -> None:
                self.init_called = False
                super().__init__(**kwargs)

            def on_start(self) -> None:
                self.init_called = True

        agent_id, config, team_id = agent_setup
        ref = InitTestAgent.start(
            agent_id=agent_id,
            config=config,
            team_id=team_id,
        )
        try:
            init_called = ref.proxy().init_called.get()
            assert init_called is True
        finally:
            ref.stop()


class TestMessageDispatch:
    """Tests for receiveMsg_<Type> pattern."""

    def test_message_handler_called(self, agent_setup) -> None:
        """Message dispatch invokes correct handler."""
        agent_id, config, team_id = agent_setup
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            # Send message and verify handler called
            msg = SampleMessage(content="hello")
            result = ref.proxy().on_receive(msg).get(timeout=5)
            assert result == "hello"

            received = ref.proxy().received_messages.get()
            assert len(received) == 1
            assert received[0].content == "hello"
        finally:
            ref.stop()

    def test_derived_message_uses_handler(self, agent_setup) -> None:
        """Derived message types use parent handler via MRO."""
        agent_id, config, team_id = agent_setup
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            # DerivedSampleMessage should use receiveMsg_SampleMessage
            msg = DerivedSampleMessage(content="derived", extra="data")
            result = ref.proxy().on_receive(msg).get(timeout=5)
            assert result == "derived"

            received = ref.proxy().received_messages.get()
            assert len(received) == 1
            assert received[0].content == "derived"
        finally:
            ref.stop()

    def test_unhandled_message_logs_warning(self, agent_setup, caplog) -> None:
        """Unhandled message type logs warning."""
        agent_id, config, team_id = agent_setup
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:

            class UnhandledMessage:
                pass

            msg = UnhandledMessage()
            ref.proxy().on_receive(msg).get(timeout=5)

            # Check warning logged
            assert any("Unknown message" in record.message for record in caplog.records)
        finally:
            ref.stop()


class TestSuperSentinel:
    """Tests for SUPER fallthrough behavior."""

    def test_super_continues_mro_search(self, agent_setup) -> None:
        """Returning SUPER causes dispatcher to continue MRO walk."""
        agent_id, config, team_id = agent_setup
        ref = SuperSampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            # receiveMsg_SampleMessage returns SUPER
            # Should fallback to receiveMsg_Message
            msg = SampleMessage(content="test")
            result = ref.proxy().on_receive(msg).get(timeout=5)

            assert result == "base_handler"
            handled = ref.proxy().handled_at_base.get()
            assert handled is True
        finally:
            ref.stop()


class TestChildActorCreation:
    """Tests for createActor and context propagation."""

    def test_create_child_actor(self, agent_setup) -> None:
        """Parent can create child actor."""
        agent_id, config, team_id = agent_setup
        config.squad_id = uuid.uuid4()
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            # Create child via proxy
            child_config = BaseConfig(name="child-agent")
            child_address = (
                ref.proxy().createActor(SampleAgent, uuid.uuid4(), child_config).get(timeout=5)
            )

            assert child_address is not None
            assert child_address.is_alive()
            assert child_address.agent_id is not None
        finally:
            ref.stop()

    def test_child_inherits_squad_id(self, agent_setup) -> None:
        """Child actor inherits parent's squad_id if not specified."""
        agent_id, config, team_id = agent_setup
        parent_squad_id = uuid.uuid4()
        config.squad_id = parent_squad_id
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            # Create child without squad_id
            child_config = BaseConfig(name="child-agent")
            child_address = (
                ref.proxy().createActor(SampleAgent, uuid.uuid4(), child_config).get(timeout=5)
            )

            child_ref = cast(ActorAddressImpl, child_address)._actor_ref
            child_squad_id = child_ref.proxy().config.get().squad_id

            assert child_squad_id == parent_squad_id
        finally:
            ref.stop()

    def test_child_overrides_squad_id(self, agent_setup) -> None:
        """Child can override parent's squad_id."""
        agent_id, config, team_id = agent_setup
        parent_squad_id = uuid.uuid4()
        child_squad_id = uuid.uuid4()
        config.squad_id = parent_squad_id
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            # Create child with explicit squad_id
            child_config = BaseConfig(name="child-agent", squad_id=child_squad_id)
            child_address = (
                ref.proxy().createActor(SampleAgent, uuid.uuid4(), child_config).get(timeout=5)
            )

            child_ref = cast(ActorAddressImpl, child_address)._actor_ref
            actual_squad_id = child_ref.proxy().config.get().squad_id

            assert actual_squad_id == child_squad_id
        finally:
            ref.stop()


class TestStateManagement:
    """Tests for state_changed, update_state, init_state."""

    def test_init_state_preserves_observer(self, agent_setup) -> None:
        """init_state preserves observer reference."""
        agent_id, config, team_id = agent_setup
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            # Get initial state observer
            initial_observer = ref.proxy().state.get()._observer

            # Create new state and initialize
            new_state = BaseState()
            ref.proxy().init_state(new_state).get(timeout=5)

            # Verify observer preserved
            updated_observer = ref.proxy().state.get()._observer
            assert updated_observer == initial_observer
        finally:
            ref.stop()

    def test_update_state_merges_updates(self, agent_setup) -> None:
        """update_state merges dictionary updates into state."""
        agent_id, config, team_id = agent_setup
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            # BaseState is simple model - just verify update_state doesn't error
            # Full state update testing requires custom state types
            updates = {}
            ref.proxy().update_state(updates).get(timeout=5)

            # Verify state exists and is accessible
            state = ref.proxy().state.get()
            assert isinstance(state, BaseState)
        finally:
            ref.stop()

    def test_update_state_failure_sets_content_type_and_content(self, agent_setup) -> None:
        """A failing update_state emits one ErrorMessage carrying the exception's name and text."""
        from akgentic.core.messages.orchestrator import ErrorMessage

        agent_id, config, team_id = agent_setup

        mock_orch_ref = MagicMock()
        mock_orch_ref.is_alive.return_value = True
        mock_orch = ActorAddressImpl(mock_orch_ref)

        ref = SampleAgent.start(
            agent_id=agent_id,
            config=config,
            team_id=team_id,
            orchestrator=mock_orch,
        )
        try:
            # An unimportable __model__ makes deserialize_object raise inside update_state.
            ref.proxy().update_state({"__model__": "nonexistent_module_xyz.NoSuchState"}).get(
                timeout=5
            )

            errors = [
                arg
                for call in mock_orch_ref.tell.call_args_list
                for arg in call[0]
                if isinstance(arg, ErrorMessage)
            ]
            assert len(errors) == 1
            assert errors[0].content_type == "ModuleNotFoundError"
            assert "nonexistent_module_xyz" in errors[0].content
        finally:
            ref.stop()


class TestStopBehavior:
    """Tests for stop and recursive cleanup."""

    def test_stop_cleans_up_children(self, agent_setup) -> None:
        """Stopping parent stops all children recursively."""
        agent_id, config, team_id = agent_setup
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            # Create child
            child_config = BaseConfig(name="child-agent")
            child_address = (
                ref.proxy().createActor(SampleAgent, uuid.uuid4(), child_config).get(timeout=5)
            )

            assert child_address.is_alive()

            # Stop parent
            ref.proxy().stop().get(timeout=5)

            # Child should be stopped
            assert not child_address.is_alive()
        finally:
            # Cleanup
            try:
                ref.stop()
            except Exception:
                pass

    def test_stop_recursively_message(self, agent_setup) -> None:
        """StopRecursively message triggers recursive stop."""
        agent_id, config, team_id = agent_setup
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            msg = StopRecursively()
            ref.proxy().on_receive(msg).get(timeout=5)

            # Agent should be stopped
            assert not ref.is_alive()
        finally:
            try:
                ref.stop()
            except Exception:
                pass


class TestProxyHelpers:
    """Tests for proxy_tell and proxy_ask."""

    def test_proxy_tell_fire_and_forget(self, agent_setup) -> None:
        """proxy_tell creates fire-and-forget proxy."""
        agent_id, config, team_id = agent_setup
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            address = ActorAddressImpl(ref)

            # Create tell proxy
            proxy = ref.proxy().proxy_tell(address, SampleAgent).get()

            assert isinstance(proxy, ProxyWrapper)
            assert proxy._ask_mode is False
        finally:
            ref.stop()

    def test_proxy_ask_blocking(self, agent_setup) -> None:
        """proxy_ask creates blocking proxy."""
        agent_id, config, team_id = agent_setup
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            address = ActorAddressImpl(ref)

            # Create ask proxy with timeout
            proxy = ref.proxy().proxy_ask(address, SampleAgent, timeout=10).get()

            assert isinstance(proxy, ProxyWrapper)
            assert proxy._ask_mode is True
            assert proxy._timeout == 10
        finally:
            ref.stop()


class TestProxyWrapper:
    """Tests for ProxyWrapper functionality."""

    def test_proxy_wrapper_ask_mode_resolves_futures(self, agent_setup) -> None:
        """Ask mode automatically resolves pykka futures."""
        agent_id, config, team_id = agent_setup
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            address = ActorAddressImpl(ref)
            wrapper = ProxyWrapper(address, ask_mode=True, timeout=5)

            # Call method - should auto-resolve future
            result = wrapper.myAddress
            assert isinstance(result, ActorAddress)
        finally:
            ref.stop()

    def test_proxy_wrapper_tell_mode_returns_none(self, agent_setup) -> None:
        """Tell mode returns None without blocking."""
        agent_id, config, team_id = agent_setup
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            address = ActorAddressImpl(ref)
            wrapper = ProxyWrapper(address, ask_mode=False)

            # Call method - should return None immediately
            result = wrapper.on_start()
            assert result is None
        finally:
            ref.stop()


class TestNoActorEventLoop:
    """Akgent no longer owns an event loop (ADR-009 §Decision.5)."""

    def test_constructed_agent_has_no_event_loop_attribute(self, agent_setup) -> None:
        """A started Akgent never creates a base ``_event_loop`` attribute (FR2)."""
        agent_id, config, team_id = agent_setup
        ref = SampleAgent.start(agent_id=agent_id, config=config, team_id=team_id)
        try:
            actor = ref._actor_weakref()
            assert actor is not None
            assert not hasattr(actor, "_event_loop")
        finally:
            ref.stop()

    def test_stop_emits_single_stop_message_without_drain(self, agent_setup) -> None:
        """Stopping an Akgent emits exactly one StopMessage and drains no loop (FR3)."""
        agent_id, config, team_id = agent_setup

        mock_orch_ref = MagicMock()
        mock_orch_ref.is_alive.return_value = True
        mock_orch = ActorAddressImpl(mock_orch_ref)

        ref = SampleAgent.start(
            agent_id=agent_id,
            config=config,
            team_id=team_id,
            orchestrator=mock_orch,
        )
        # No base loop was ever created.
        actor = ref._actor_weakref()
        assert actor is not None
        assert not hasattr(actor, "_event_loop")

        # Block until the actor thread is fully joined: on_stop() (and its
        # StopMessage notify) runs during Pykka's shutdown, after the run loop
        # exits — a proxy stop().get() can return before it completes. The
        # blocking ActorRef.stop() guarantees on_stop has finished here.
        ref.stop(block=True)

        from akgentic.core.messages.orchestrator import StopMessage

        stop_calls = [
            call
            for call in mock_orch_ref.tell.call_args_list
            if any(isinstance(arg, StopMessage) for arg in call[0])
        ]
        assert len(stop_calls) == 1

    def test_drain_machinery_absent_from_class(self) -> None:
        """The drain helpers are gone from Akgent and the module (FR3)."""
        assert not hasattr(Akgent, "_drain_event_loop")
        assert not hasattr(Akgent, "_cancel_pending_tasks")

        import akgentic.core.agent as agent_module

        assert not hasattr(agent_module, "_evict_anyio_run_vars")


class TestOrchestratorIntegration:
    """Tests for orchestrator notification integration."""

    def test_notify_orchestrator_sends_start_message(self, agent_setup) -> None:
        """Agent notifies orchestrator on initialization."""
        agent_id, config, team_id = agent_setup

        # Create mock orchestrator
        mock_orch_ref = MagicMock()
        mock_orch_ref.is_alive.return_value = True
        mock_orch = ActorAddressImpl(mock_orch_ref)

        ref = SampleAgent.start(
            agent_id=agent_id,
            config=config,
            team_id=team_id,
            orchestrator=mock_orch,
        )
        try:
            # Verify StartMessage sent
            assert mock_orch_ref.tell.called
            call_args = mock_orch_ref.tell.call_args_list[0][0]
            from akgentic.core.messages.orchestrator import StartMessage

            assert any(isinstance(arg, StartMessage) for arg in call_args)
        finally:
            ref.stop()

    def test_send_notifies_orchestrator(self, agent_setup) -> None:
        """send() notifies orchestrator with SentMessage."""
        agent_id, config, team_id = agent_setup

        # Create mock orchestrator
        mock_orch_ref = MagicMock()
        mock_orch_ref.is_alive.return_value = True
        mock_orch = ActorAddressImpl(mock_orch_ref)

        ref = SampleAgent.start(
            agent_id=agent_id,
            config=config,
            team_id=team_id,
            orchestrator=mock_orch,
        )
        try:
            # Create recipient
            recipient_ref = SampleAgent.start(
                agent_id=uuid.uuid4(),
                config=BaseConfig(),
                team_id=team_id,
            )
            recipient_address = ActorAddressImpl(recipient_ref)

            # Send message
            msg = SampleMessage(content="test")
            ref.proxy().send(recipient_address, msg).get(timeout=5)

            # Verify SentMessage sent to orchestrator
            from akgentic.core.messages.orchestrator import SentMessage

            sent_calls = [
                call
                for call in mock_orch_ref.tell.call_args_list
                if any(isinstance(arg, SentMessage) for arg in call[0])
            ]
            assert len(sent_calls) > 0

            recipient_ref.stop()
        finally:
            ref.stop()


##
## Turn-boundary state checkpoints (epic 25, story 25-2)
##


class _CountingState(BaseState):
    """State that counts its serializations and can be armed to fail one.

    ``_dump_calls`` is the load-bearing probe for "no serialization happened":
    an unobserved state must cost nothing per turn, and silence alone cannot
    prove that. ``_explode`` simulates a state that cannot be serialized.
    """

    value: int = 0
    _dump_calls: int = PrivateAttr(default=0)
    _explode: bool = PrivateAttr(default=False)

    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
        self._dump_calls += 1
        if self._explode:
            raise RuntimeError("cannot serialize")
        return super().model_dump_json(*args, **kwargs)


class MutateMessage(Message):
    """Turn whose handler mutates state and never notifies."""


class CleanMessage(Message):
    """Turn whose handler changes nothing."""


class NotifyingMutateMessage(Message):
    """Turn whose handler mutates state and notifies explicitly."""


class RaisingMutateMessage(Message):
    """Turn whose handler mutates state and then raises."""


class WarningMutateMessage(Message):
    """Turn whose handler mutates state and then raises a WarningError."""


class RawControl:
    """Plain non-Message control object — an internal path, not a team turn."""


class ObservedAgent(Akgent[BaseConfig, _CountingState]):
    """Agent that observes its own state, as akgentic-agent's BaseAgent does.

    Base ``Akgent`` never attaches an observer to its own state, so without this
    every checkpoint assertion would pass through ``notify_if_changed()``'s
    no-observer early return and prove nothing.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = _CountingState().observer(self)

    def receiveMsg_MutateMessage(self, msg: MutateMessage, sender: Any) -> str:
        self.state.value += 1
        return "mutated"

    def receiveMsg_CleanMessage(self, msg: CleanMessage, sender: Any) -> str:
        return "clean"

    def receiveMsg_NotifyingMutateMessage(self, msg: NotifyingMutateMessage, sender: Any) -> str:
        self.state.value += 1
        # The state-side call: it stamps the baseline, so the checkpoint that
        # follows sees an equal digest and stays silent.
        self.state.notify_state_change()
        return "notified"

    def receiveMsg_RaisingMutateMessage(self, msg: RaisingMutateMessage, sender: Any) -> None:
        self.state.value += 1
        raise ValueError("boom")

    def receiveMsg_WarningMutateMessage(self, msg: WarningMutateMessage, sender: Any) -> None:
        self.state.value += 1
        raise WarningError("careful")

    def receiveMsg_RawControl(self, msg: RawControl, sender: Any) -> str:
        self.state.value += 1
        return "raw"

    def touch_state(self) -> None:
        """Mutate state outside any message turn (direct proxy call)."""
        self.state.value += 1


class UnobservedAgent(Akgent[BaseConfig, _CountingState]):
    """Agent holding a _CountingState with NO observer attached."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = _CountingState()

    def receiveMsg_MutateMessage(self, msg: MutateMessage, sender: Any) -> str:
        self.state.value += 1
        return "mutated"


def _mock_orchestrator() -> tuple[MagicMock, ActorAddressImpl]:
    """Build a mock orchestrator whose ``tell`` records telemetry in call order."""
    mock_orch_ref = MagicMock()
    mock_orch_ref.is_alive.return_value = True
    return mock_orch_ref, ActorAddressImpl(mock_orch_ref)


def _telemetry(mock_orch_ref: MagicMock) -> list[Message]:
    """Every Message told to the orchestrator, in call order."""
    return [
        arg
        for call in mock_orch_ref.tell.call_args_list
        for arg in call[0]
        if isinstance(arg, Message)
    ]


def _types(mock_orch_ref: MagicMock) -> list[type]:
    """Telemetry reduced to its message types, in call order."""
    return [type(message) for message in _telemetry(mock_orch_ref)]


def _checkpoint_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """WARNING records emitted by the agent module."""
    return [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and record.name == "akgentic.core.agent"
    ]


@pytest.fixture
def observed_agent(agent_setup: tuple[uuid.UUID, BaseConfig, uuid.UUID]) -> Iterator[Any]:
    """Started ObservedAgent + its mock orchestrator, counted from a clean slate.

    Attaching the observer notifies at construction (deliberate — it seeds the
    restore replay), so the mock is reset right after start(); without that every
    "exactly one" assertion below would be off by one.
    """
    agent_id, config, team_id = agent_setup
    mock_orch_ref, mock_orch = _mock_orchestrator()
    ref = ObservedAgent.start(
        agent_id=agent_id,
        config=config,
        team_id=team_id,
        orchestrator=mock_orch,
    )
    mock_orch_ref.reset_mock()
    yield ref, mock_orch_ref
    try:
        ref.stop()
    except Exception:
        pass


class TestTurnBoundaryCheckpoint:
    """A turn that changed the state publishes it, before it reports completion."""

    def test_mutating_handler_checkpoints_before_processed(self, observed_agent: Any) -> None:
        """A handler that mutates and never notifies still publishes once (AC #2)."""
        ref, mock_orch_ref = observed_agent

        msg = MutateMessage()
        assert ref.proxy().on_receive(msg).get(timeout=5) == "mutated"

        types = _types(mock_orch_ref)
        assert types.count(StateChangedMessage) == 1
        # Ordering, not mere presence: the snapshot must be durable before the
        # orchestrator sees the turn as complete.
        assert types.index(StateChangedMessage) < types.index(ProcessedMessage)

        changed = [m for m in _telemetry(mock_orch_ref) if isinstance(m, StateChangedMessage)][0]
        assert cast(_CountingState, changed.state).value == 1
        # The checkpoint runs while _current_message is still set, so the
        # notification is attributable to the message that caused it. Without
        # this, clearing _current_message before the checkpoint would drop the
        # correlation with every other assertion here still green.
        assert changed.parent_id == msg.id

    def test_clean_turn_emits_no_state_change(self, observed_agent: Any) -> None:
        """A handler that changes nothing publishes nothing (AC #3)."""
        ref, mock_orch_ref = observed_agent

        assert ref.proxy().on_receive(CleanMessage()).get(timeout=5) == "clean"

        types = _types(mock_orch_ref)
        assert types.count(StateChangedMessage) == 0
        assert types.count(ReceivedMessage) == 1
        assert types.count(ProcessedMessage) == 1

    def test_raw_object_branch_never_checkpoints(self, observed_agent: Any) -> None:
        """A non-Message object is an internal control path, not a turn (AC #4)."""
        ref, mock_orch_ref = observed_agent

        assert ref.proxy().on_receive(RawControl()).get(timeout=5) == "raw"

        # The handler really did mutate — the silence below is the branch, not a no-op.
        assert ref.proxy().state.get().value == 1
        assert _types(mock_orch_ref).count(StateChangedMessage) == 0

    def test_explicit_notify_does_not_double_publish(self, observed_agent: Any) -> None:
        """A diligent handler still publishes exactly once (AC #5, NFR4)."""
        ref, mock_orch_ref = observed_agent

        assert ref.proxy().on_receive(NotifyingMutateMessage()).get(timeout=5) == "notified"

        assert _types(mock_orch_ref).count(StateChangedMessage) == 1


class TestFailurePathCheckpoint:
    """A handler that mutated and then raised has already changed the world."""

    def test_raising_handler_checkpoints_before_error(self, observed_agent: Any) -> None:
        """State survives a failing turn, ahead of the failure report (AC #6)."""
        ref, mock_orch_ref = observed_agent

        msg = RaisingMutateMessage()
        # tell(), not proxy().on_receive().get(): Pykka routes to _handle_failure
        # only when the failing message carries no reply_to.
        ref.tell(msg)
        ref.proxy().agent_id.get(timeout=5)  # barrier: mailbox drained past msg

        types = _types(mock_orch_ref)
        assert types.count(StateChangedMessage) == 1
        assert types.index(StateChangedMessage) < types.index(ProcessedMessage)
        assert types.index(StateChangedMessage) < types.index(ErrorMessage)

        errors = [m for m in _telemetry(mock_orch_ref) if isinstance(m, ErrorMessage)]
        assert len(errors) == 1
        assert errors[0].content_type == "ValueError"
        assert errors[0].content == "boom"
        assert errors[0].traceback is not None
        assert errors[0].current_message is not None
        assert errors[0].current_message.id == msg.id

    def test_warning_error_path_checkpoints_and_stays_unchanged(self, observed_agent: Any) -> None:
        """A WarningError turn persists state and still reports a warning (AC #6)."""
        ref, mock_orch_ref = observed_agent

        msg = WarningMutateMessage()
        ref.tell(msg)
        ref.proxy().agent_id.get(timeout=5)

        types = _types(mock_orch_ref)
        assert types.count(StateChangedMessage) == 1
        assert types.count(ErrorMessage) == 0
        assert types.index(StateChangedMessage) < types.index(WarningMessage)

        warnings = [m for m in _telemetry(mock_orch_ref) if isinstance(m, WarningMessage)]
        assert len(warnings) == 1
        assert warnings[0].content_type == "WarningError"
        assert warnings[0].content == "careful"
        assert warnings[0].current_message is not None
        assert warnings[0].current_message.id == msg.id


class TestStopPathCheckpoint:
    """State mutated outside any turn is still persisted when the agent goes."""

    def test_state_touched_outside_a_turn_is_checkpointed_on_stop(
        self, observed_agent: Any
    ) -> None:
        """A proxy-call mutation publishes at on_stop, before StopMessage (AC #7)."""
        ref, mock_orch_ref = observed_agent

        # Pykka handles proxy calls internally: this never reaches on_receive,
        # so no turn-boundary checkpoint fires for it.
        ref.proxy().touch_state().get(timeout=5)
        assert _types(mock_orch_ref).count(StateChangedMessage) == 0

        # Blocking stop: on_stop runs during Pykka's shutdown, after the run loop
        # exits, so a proxy stop().get() can return before the checkpoint happened.
        ref.stop(block=True)

        types = _types(mock_orch_ref)
        assert types.count(StateChangedMessage) == 1
        assert types.index(StateChangedMessage) < types.index(StopMessage)


class TestCheckpointNeverBreaksTheTurn:
    """A state that cannot serialize costs a WARNING, never the turn."""

    def test_serialization_failure_leaves_the_turn_intact(
        self, observed_agent: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A failing checkpoint is announced and swallowed (AC #8, NFR5)."""
        ref, mock_orch_ref = observed_agent

        # Arm AFTER start: observer() stamps a baseline via model_dump_json(), so a
        # state that always raises would blow up in __init__, not in the turn.
        ref.proxy().state.get()._explode = True
        caplog.set_level(logging.WARNING)
        caplog.clear()

        # No exception escapes and the handler's return value still comes back.
        assert ref.proxy().on_receive(MutateMessage()).get(timeout=5) == "mutated"

        types = _types(mock_orch_ref)
        assert types.count(ProcessedMessage) == 1
        assert types.count(StateChangedMessage) == 0

        warnings = _checkpoint_warnings(caplog)
        assert len(warnings) == 1
        assert cast(BaseConfig, ref.proxy().config.get()).name in warnings[0].getMessage()
        assert warnings[0].exc_info is not None

    def test_serialization_failure_leaves_the_error_report_intact(
        self, observed_agent: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A failing checkpoint never masks or reorders the failure (AC #9, NFR5)."""
        ref, mock_orch_ref = observed_agent

        ref.proxy().state.get()._explode = True
        caplog.set_level(logging.WARNING)
        caplog.clear()

        msg = RaisingMutateMessage()
        ref.tell(msg)
        ref.proxy().agent_id.get(timeout=5)

        # Same ErrorMessage as the control run in TestFailurePathCheckpoint.
        errors = [m for m in _telemetry(mock_orch_ref) if isinstance(m, ErrorMessage)]
        assert len(errors) == 1
        assert errors[0].content_type == "ValueError"
        assert errors[0].content == "boom"
        assert errors[0].traceback is not None
        assert errors[0].current_message is not None
        assert errors[0].current_message.id == msg.id

        assert _types(mock_orch_ref).count(StateChangedMessage) == 0
        assert len(_checkpoint_warnings(caplog)) == 1


class TestUnobservedStateCostsNothing:
    """No observer, no serialization — the checkpoint is free (AC #10, NFR1)."""

    def test_agent_without_observer_never_serializes_its_state(
        self, agent_setup: tuple[uuid.UUID, BaseConfig, uuid.UUID]
    ) -> None:
        """A base Akgent emits nothing and serializes nothing on a mutating turn."""
        agent_id, config, team_id = agent_setup
        mock_orch_ref, mock_orch = _mock_orchestrator()

        ref = UnobservedAgent.start(
            agent_id=agent_id,
            config=config,
            team_id=team_id,
            orchestrator=mock_orch,
        )
        try:
            mock_orch_ref.reset_mock()
            assert ref.proxy().on_receive(MutateMessage()).get(timeout=5) == "mutated"

            state = ref.proxy().state.get()
            assert state.value == 1
            assert state._dump_calls == 0
            assert _types(mock_orch_ref).count(StateChangedMessage) == 0
        finally:
            ref.stop()

    def test_orchestrator_never_serializes_its_state_on_a_message(self) -> None:
        """A live Orchestrator holds an unobserved state and pays nothing per message."""
        orch_ref = Orchestrator.start(config=BaseConfig(name="orch", role="Orchestrator"))
        try:
            state = _CountingState()
            orch_ref.proxy().init_state(state).get(timeout=5)
            state._dump_calls = 0

            orch_ref.proxy().on_receive(EventMessage(event="ping")).get(timeout=5)

            assert state._dump_calls == 0
        finally:
            orch_ref.stop()


class TestInitStateStaysUnconditional:
    """Restore always speaks, even when nothing looks different."""

    def test_init_state_notifies_even_for_an_identical_state(self, observed_agent: Any) -> None:
        """init_state() gets no dirty check (AC #11, FR9).

        The incoming state carries its own stamped baseline, exactly as a state
        that has already been published does — so converting init_state() to
        notify_if_changed() would suppress this notification and turn the test
        red. That notification is what seeds the cursor-0 replay for a restored
        running team.
        """
        ref, mock_orch_ref = observed_agent

        identical = _CountingState(value=0)
        identical.notify_state_change()  # stamp the baseline; no observer yet, so silent
        assert identical.model_dump_json() == ref.proxy().state.get().model_dump_json()

        ref.proxy().init_state(identical).get(timeout=5)

        assert _types(mock_orch_ref).count(StateChangedMessage) == 1
