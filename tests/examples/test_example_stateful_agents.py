"""Tests for Stateful Agents example (Story 5.4).

Verifies the example demonstrates state management patterns:
- Custom state types (CounterState) with observer pattern
- State initialization and observer attachment
- State mutations with explicit notification
- Orchestrator tracking of state changes
- Querying final state via Orchestrator.get_states()
"""

import importlib.util
import sys
import time
from pathlib import Path

from akgentic import ActorSystem, BaseConfig, BaseState, Orchestrator
from akgentic.messages import Message


class TestCounterStateDefinition:
    """Tests for CounterState class definition."""

    def test_counter_state_can_be_imported(self):
        """CounterState class can be imported from example."""
        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"
        spec = importlib.util.spec_from_file_location("stateful_agents", example_path)
        assert spec is not None, f"Example file not found: {example_path}"
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None, "No loader for example module"
        spec.loader.exec_module(module)

        assert hasattr(module, "CounterState"), "CounterState not defined in example"
        assert issubclass(module.CounterState, BaseState), "CounterState must extend BaseState"

    def test_counter_state_has_required_fields(self):
        """CounterState has count, history, and last_operation fields."""
        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"
        spec = importlib.util.spec_from_file_location("stateful_agents", example_path)
        assert spec is not None, f"Example file not found: {example_path}"
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None, "No loader for example module"
        spec.loader.exec_module(module)

        state = module.CounterState()
        assert hasattr(state, "count"), "CounterState missing 'count' field"
        assert hasattr(state, "history"), "CounterState missing 'history' field"
        assert hasattr(state, "last_operation"), "CounterState missing 'last_operation' field"

    def test_counter_state_initial_values(self):
        """CounterState initializes with correct default values."""
        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"
        spec = importlib.util.spec_from_file_location("stateful_agents", example_path)
        assert spec is not None, f"Example file not found: {example_path}"
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None, "No loader for example module"
        spec.loader.exec_module(module)

        state = module.CounterState()
        assert state.count == 0, "count should default to 0"
        assert state.history == [], "history should default to empty list"
        assert state.last_operation == "", "last_operation should default to empty string"


class TestCounterMessageTypes:
    """Tests for message types."""

    def test_increment_message_definition(self):
        """IncrementMessage has amount and label fields."""
        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"
        spec = importlib.util.spec_from_file_location("stateful_agents", example_path)
        assert spec is not None, f"Example file not found: {example_path}"
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None, "No loader for example module"
        spec.loader.exec_module(module)

        assert hasattr(module, "IncrementMessage"), "IncrementMessage not defined"
        assert issubclass(module.IncrementMessage, Message), "IncrementMessage must extend Message"

        msg = module.IncrementMessage(amount=5, label="test")  # type: ignore
        assert msg.amount == 5  # type: ignore
        assert msg.label == "test"  # type: ignore

    def test_reset_message_definition(self):
        """ResetMessage has reason field."""
        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"
        spec = importlib.util.spec_from_file_location("stateful_agents", example_path)
        assert spec is not None, f"Example file not found: {example_path}"
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None, "No loader for example module"
        spec.loader.exec_module(module)

        assert hasattr(module, "ResetMessage"), "ResetMessage not defined"
        assert issubclass(module.ResetMessage, Message), "ResetMessage must extend Message"

        msg = module.ResetMessage(reason="test reset")  # type: ignore
        assert msg.reason == "test reset"  # type: ignore


class TestCounterAgentStateInitialization:
    """Tests for CounterAgent state initialization."""

    def test_counter_agent_initializes_state(self):
        """CounterAgent.init() initializes state."""
        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"
        spec = importlib.util.spec_from_file_location("stateful_agents", example_path)
        assert spec is not None, f"Example file not found: {example_path}"
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None, "No loader for example module"
        spec.loader.exec_module(module)

        system = ActorSystem()
        try:
            counter_addr = system.createActor(
                module.CounterAgent,
                config=BaseConfig(name="test-counter", role="Counter"),
            )

            # Give time for initialization
            time.sleep(0.1)

            # Verify agent was created
            assert counter_addr is not None
            assert counter_addr.is_alive()

        finally:
            system.shutdown(timeout=5)

    def test_counter_agent_attaches_observer(self):
        """CounterAgent attaches itself as observer to state."""
        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"
        spec = importlib.util.spec_from_file_location("stateful_agents", example_path)
        assert spec is not None, f"Example file not found: {example_path}"
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None, "No loader for example module"
        spec.loader.exec_module(module)

        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            # Create agent with orchestrator reference
            counter_ref = module.CounterAgent.start(
                config=BaseConfig(name="test-counter", role="Counter"),
                orchestrator=orchestrator_addr,
            )
            from akgentic import ActorAddressImpl

            counter_addr = ActorAddressImpl(counter_ref)

            # Give time for initialization
            time.sleep(0.2)

            # Query orchestrator for state - should be tracked after init
            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)
            states = orch_proxy.get_states()

            # Should have tracked the agent's initial state
            assert len(states) > 0, "Observer should track state during init"

        finally:
            system.shutdown(timeout=5)


class TestCounterAgentStateMutations:
    """Tests for state mutations through message handlers."""

    def test_increment_message_increments_count(self, capsys):
        """IncrementMessage increments count and notifies."""
        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"
        spec = importlib.util.spec_from_file_location("stateful_agents", example_path)
        assert spec is not None, f"Example file not found: {example_path}"
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None, "No loader for example module"
        spec.loader.exec_module(module)

        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            # Create agent with orchestrator reference
            counter_ref = module.CounterAgent.start(
                config=BaseConfig(name="test-counter", role="Counter"),
                orchestrator=orchestrator_addr,
            )
            from akgentic import ActorAddressImpl

            counter_addr = ActorAddressImpl(counter_ref)

            # Send increment message
            system.tell(
                counter_addr,
                module.IncrementMessage(amount=5, label="test increment"),
            )

            # Wait for processing
            time.sleep(0.2)

            # Check output
            captured = capsys.readouterr()
            assert "Incremented by 5" in captured.out
            assert "count: 5" in captured.out

            # Query orchestrator for final state
            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)
            states = orch_proxy.get_states()

            # Should have a state with count=5
            assert len(states) > 0, "Orchestrator should track agent state"
            final_state = next(iter(states.values()))
            assert isinstance(final_state, module.CounterState)
            assert final_state.count == 5, f"Expected count=5, got {final_state.count}"  # type: ignore

        finally:
            system.shutdown(timeout=5)

    def test_reset_message_resets_count(self, capsys):
        """ResetMessage resets count to zero and notifies."""
        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"
        spec = importlib.util.spec_from_file_location("stateful_agents", example_path)
        assert spec is not None, f"Example file not found: {example_path}"
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None, "No loader for example module"
        spec.loader.exec_module(module)

        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            # Create agent with orchestrator reference
            counter_ref = module.CounterAgent.start(
                config=BaseConfig(name="test-counter", role="Counter"),
                orchestrator=orchestrator_addr,
            )
            from akgentic import ActorAddressImpl

            counter_addr = ActorAddressImpl(counter_ref)

            # Send increment then reset
            system.tell(
                counter_addr,
                module.IncrementMessage(amount=10, label="increment"),
            )
            time.sleep(0.1)

            system.tell(
                counter_addr,
                module.ResetMessage(reason="test reset"),
            )

            # Wait for processing
            time.sleep(0.2)

            # Check output
            captured = capsys.readouterr()
            assert "Reset" in captured.out
            assert "count: 0" in captured.out

            # Query orchestrator for final state
            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)
            states = orch_proxy.get_states()

            # Should have a state with count=0
            assert len(states) > 0
            final_state = next(iter(states.values()))
            assert isinstance(final_state, module.CounterState)
            assert final_state.count == 0, f"Expected count=0 after reset, got {final_state.count}"  # type: ignore

        finally:
            system.shutdown(timeout=5)

    def test_history_tracks_operations(self):
        """State history field tracks all operations."""
        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"
        spec = importlib.util.spec_from_file_location("stateful_agents", example_path)
        assert spec is not None, f"Example file not found: {example_path}"
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None, "No loader for example module"
        spec.loader.exec_module(module)

        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            # Create agent with orchestrator reference
            counter_ref = module.CounterAgent.start(
                config=BaseConfig(name="test-counter", role="Counter"),
                orchestrator=orchestrator_addr,
            )
            from akgentic import ActorAddressImpl

            counter_addr = ActorAddressImpl(counter_ref)

            # Send multiple operations
            system.tell(
                counter_addr,
                module.IncrementMessage(amount=5, label="op1"),
            )
            time.sleep(0.1)

            system.tell(
                counter_addr,
                module.IncrementMessage(amount=3, label="op2"),
            )
            time.sleep(0.2)

            # Query orchestrator for final state
            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)
            states = orch_proxy.get_states()

            # Check history
            assert len(states) > 0
            final_state = next(iter(states.values()))
            assert isinstance(final_state, module.CounterState)
            assert "op1" in final_state.history  # type: ignore
            assert "op2" in final_state.history  # type: ignore

        finally:
            system.shutdown(timeout=5)


class TestOrchestratorStateTracking:
    """Tests for Orchestrator tracking of state changes."""

    def test_orchestrator_tracks_state_changes(self):
        """Orchestrator.get_states() returns tracked agent states."""
        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"
        spec = importlib.util.spec_from_file_location("stateful_agents", example_path)
        assert spec is not None, f"Example file not found: {example_path}"
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None, "No loader for example module"
        spec.loader.exec_module(module)

        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            # Create agent with orchestrator reference
            counter_ref = module.CounterAgent.start(
                config=BaseConfig(name="test-counter", role="Counter"),
                orchestrator=orchestrator_addr,
            )
            from akgentic import ActorAddressImpl

            counter_addr = ActorAddressImpl(counter_ref)

            # Send some messages
            system.tell(
                counter_addr,
                module.IncrementMessage(amount=5, label="test"),
            )
            time.sleep(0.2)

            # Query orchestrator
            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)
            states = orch_proxy.get_states()

            # Should have tracked the agent's state
            assert isinstance(states, dict), "get_states() should return dict"
            assert len(states) > 0, "Orchestrator should track agent states"

        finally:
            system.shutdown(timeout=5)

    def test_orchestrator_tracks_all_state_mutations(self):
        """Orchestrator records state mutations through get_states()."""
        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"
        spec = importlib.util.spec_from_file_location("stateful_agents", example_path)
        assert spec is not None, f"Example file not found: {example_path}"
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None, "No loader for example module"
        spec.loader.exec_module(module)

        system = ActorSystem()
        try:
            orchestrator_addr = system.createActor(
                Orchestrator,
                config=BaseConfig(name="orchestrator", role="Orchestrator"),
            )

            # Create agent with orchestrator reference
            counter_ref = module.CounterAgent.start(
                config=BaseConfig(name="test-counter", role="Counter"),
                orchestrator=orchestrator_addr,
            )
            from akgentic import ActorAddressImpl

            counter_addr = ActorAddressImpl(counter_ref)

            # Send increment
            system.tell(
                counter_addr,
                module.IncrementMessage(amount=5, label="inc1"),
            )
            time.sleep(0.1)

            # Send another increment
            system.tell(
                counter_addr,
                module.IncrementMessage(amount=3, label="inc2"),
            )
            time.sleep(0.2)

            # Get final state
            orch_proxy = system.proxy_ask(orchestrator_addr, Orchestrator)
            states = orch_proxy.get_states()

            # Should have tracked the state with 2 mutations in history
            assert len(states) > 0, "Orchestrator should track agent states"
            final_state = next(iter(states.values()))
            assert isinstance(final_state, module.CounterState)
            assert len(final_state.history) == 2, (  # type: ignore
                f"Expected 2 mutations, got {len(final_state.history)}"  # type: ignore
            )
            assert final_state.count == 8, f"Expected count=8 (5+3), got {final_state.count}"  # type: ignore

        finally:
            system.shutdown(timeout=5)


class TestEndToEndExecution:
    """Tests for complete example execution."""

    def test_example_runs_without_exceptions(self):
        """Example runs end-to-end without errors."""
        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"

        import subprocess

        result = subprocess.run(
            [sys.executable, str(example_path)],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(example_path.parent.parent),
        )

        # Should complete successfully
        assert result.returncode == 0, f"Example failed with stderr: {result.stderr}"

        # Should produce expected output
        assert "[Stateful Agents]" in result.stdout
        assert "Orchestrator" in result.stdout or "CounterAgent" in result.stdout

    def test_example_demonstrates_state_tracking(self):
        """Example output shows state tracking and mutations."""
        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"

        import subprocess

        result = subprocess.run(
            [sys.executable, str(example_path)],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(example_path.parent.parent),
        )

        assert result.returncode == 0
        assert "Incremented" in result.stdout, "Should show increment operations"
        assert "Reset" in result.stdout, "Should show reset operation"
        assert "state" in result.stdout.lower(), "Should mention state tracking"

    def test_example_completes_within_timeout(self):
        """Example completes execution within 5 seconds."""
        import subprocess
        import time

        example_path = Path(__file__).parent.parent.parent / "examples" / "04_stateful_agents.py"

        start = time.time()
        result = subprocess.run(
            [sys.executable, str(example_path)],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(example_path.parent.parent),
        )
        elapsed = time.time() - start

        assert result.returncode == 0, f"Example failed: {result.stderr}"
        assert elapsed < 5, f"Example took {elapsed:.2f}s, should be <5s"
