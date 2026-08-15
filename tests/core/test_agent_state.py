"""Tests for agent state management with observer pattern."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, PrivateAttr

from akgentic.core.agent_state import BaseState


class Notification(BaseModel):
    """Notification payload - plain BaseModel, not BaseState."""

    count: int = 0
    dummy_field: str | None = None


class WorkerState(BaseState):
    """Custom state model that extends BaseState with observable fields."""

    dummy_field: str = "default"


class RecordingObserver:
    """Observer that records a snapshot of every state it is notified about.

    Tests assert on ``len(observer.states)`` so that "notified once" is
    distinguishable from "notified twice" - several acceptance criteria turn
    on exactly that difference.

    Each notification is stored as a ``serializable_copy()``, matching what
    the production observer does (``Akgent.notify_state_change`` copies before
    putting the state on a ``StateChangedMessage``). Storing the live object
    instead would make every recorded entry an alias of the same instance, so
    a later assertion on recorded *content* would silently read the newest
    value - the trap ``test_notification_captures_state_snapshot`` pins for
    the other observer in this module.
    """

    def __init__(self) -> None:
        self.states: list[BaseState] = []

    def notify_state_change(self, state: BaseState) -> None:
        """Record a snapshot of the notified state."""
        self.states.append(state.serializable_copy())


class Nested(BaseModel):
    """Plain nested model - not a BaseState, so it has no observer of its own."""

    field: str = "initial"


class DeepState(BaseState):
    """State whose interesting mutations all happen *inside* its fields.

    ``items.append(...)``, ``by_id[k] = v`` and ``nested.field = v`` never
    rebind an attribute on the state object itself, which is why change
    detection has to be a serialization digest rather than a dirty flag.
    """

    items: list[str] = []
    by_id: dict[str, int] = {}
    nested: Nested = Nested()


class CountingState(BaseState):
    """State that counts its own serializations.

    Lets a test assert that ``notify_if_changed()`` *skipped* serializing on
    the detached path, rather than only that no notification was delivered -
    an implementation that serialized first and checked the observer second
    would pass the weaker assertion.
    """

    _dump_calls: int = PrivateAttr(default=0)

    value: str = "initial"

    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
        """Count the call, then serialize normally."""
        self._dump_calls += 1
        return super().model_dump_json(*args, **kwargs)


class MockObserver:
    """Mock observer that creates Notifications when WorkerState changes.

    When state_changed() is called, it extracts data from the state,
    creates a Notification, and stores it for testing verification.
    """

    def __init__(self) -> None:
        self.notifications: list[Notification] = []

    def notify_state_change(self, state: BaseState) -> None:
        """Called when observed state changes.

        Extracts data from state and creates a notification record.
        """
        count = len(self.notifications) + 1
        dummy_field = getattr(state, "dummy_field", None)
        notification = Notification(count=count, dummy_field=dummy_field)
        self.notifications.append(notification)


class TestAkgentStateObserver:
    """Test the observer protocol definition."""

    def test_observer_protocol_defined(self) -> None:
        """Verify observer has notify_state_change method."""
        observer = MockObserver()
        assert hasattr(observer, "notify_state_change")

    def test_observer_receives_state_changes(self) -> None:
        """Verify observer receives and records state changes."""
        observer = MockObserver()
        state = WorkerState(dummy_field="test")

        # Manually trigger state change
        observer.notify_state_change(state)

        # Observer should have recorded the notification
        assert len(observer.notifications) == 1
        assert observer.notifications[0].count == 1
        assert observer.notifications[0].dummy_field == "test"


class TestBaseState:
    """Test BaseState observer pattern mechanics."""

    def test_base_state_instantiation(self) -> None:
        """Test BaseState can be instantiated with no observer."""
        state = BaseState()
        assert state._observer is None

    def test_observer_attachment(self) -> None:
        """Test observer can be attached and returns self for chaining."""
        state = BaseState()
        observer = MockObserver()

        result = state.observer(observer)

        assert state._observer is observer
        assert result is state

    def test_observer_triggers_notification_on_attach(self) -> None:
        """Test attaching observer triggers immediate notification."""
        state = BaseState()
        observer = MockObserver()

        state.observer(observer)

        # Should have one notification from attachment
        assert len(observer.notifications) == 1

    def test_notify_state_change(self) -> None:
        """Test notify_state_change triggers observer callback."""
        state = BaseState()
        observer = MockObserver()
        state.observer(observer)
        observer.notifications.clear()

        state.notify_state_change()

        assert len(observer.notifications) == 1

    def test_notify_without_observer(self) -> None:
        """Test notify_state_change doesn't raise when no observer attached."""
        state = BaseState()

        # Should not raise
        state.notify_state_change()

    def test_serializable_copy_excludes_observer(self) -> None:
        """Test serializable_copy creates copy without observer reference."""
        state = BaseState()
        observer = MockObserver()
        state.observer(observer)

        copy = state.serializable_copy()

        assert copy._observer is None
        assert copy is not state

    def test_detach_observer(self) -> None:
        """Test observer can be detached by setting to None."""
        state = BaseState()
        observer = MockObserver()
        state.observer(observer)

        ## Notification when attaching observer
        assert len(observer.notifications) == 1

        observer.notifications.clear()

        # Detach observer
        state.observer(None)

        # Observer was set to None BEFORE notify_state_change() call,
        # so no notification occurs
        assert len(observer.notifications) == 0

        # Explicit notify should also not trigger
        state.notify_state_change()
        assert len(observer.notifications) == 0

    def test_observer_replacement(self) -> None:
        """Test replacing one observer with another."""
        state = BaseState()
        observer1 = MockObserver()
        observer2 = MockObserver()

        # Attach first observer
        state.observer(observer1)
        assert len(observer1.notifications) == 1

        # Replace with second observer
        state.observer(observer2)
        assert len(observer2.notifications) == 1

        # Only observer2 should receive new notifications
        observer1.notifications.clear()
        observer2.notifications.clear()

        state.notify_state_change()

        assert len(observer1.notifications) == 0
        assert len(observer2.notifications) == 1


class TestCustomState:
    """Test custom states extending BaseState."""

    def test_worker_state_instantiation(self) -> None:
        """Test WorkerState can be instantiated with default values."""
        state = WorkerState()
        assert state.dummy_field == "default"
        assert state._observer is None

    def test_worker_state_with_custom_value(self) -> None:
        """Test WorkerState can be instantiated with custom values."""
        state = WorkerState(dummy_field="custom")
        assert state.dummy_field == "custom"

    def test_worker_state_observer_pattern(self) -> None:
        """Test WorkerState notifies observer when state changes."""
        state = WorkerState(dummy_field="initial")
        observer = MockObserver()

        # Attach observer
        state.observer(observer)

        # Should have one notification from attachment
        assert len(observer.notifications) == 1
        assert observer.notifications[0].dummy_field == "initial"

        # Change state and notify
        observer.notifications.clear()
        state.dummy_field = "updated"
        state.notify_state_change()

        # Should have one notification from the update
        assert len(observer.notifications) == 1
        assert observer.notifications[0].dummy_field == "updated"

    def test_multiple_state_changes(self) -> None:
        """Test observer receives multiple notifications for multiple changes."""
        state = WorkerState(dummy_field="v1")
        observer = MockObserver()
        state.observer(observer)
        observer.notifications.clear()

        # Multiple state changes
        state.dummy_field = "v2"
        state.notify_state_change()

        state.dummy_field = "v3"
        state.notify_state_change()

        state.dummy_field = "v4"
        state.notify_state_change()

        # Should have three notifications
        assert len(observer.notifications) == 3
        assert observer.notifications[0].count == 1
        assert observer.notifications[0].dummy_field == "v2"
        assert observer.notifications[1].count == 2
        assert observer.notifications[1].dummy_field == "v3"
        assert observer.notifications[2].count == 3
        assert observer.notifications[2].dummy_field == "v4"

    def test_worker_state_serializable_copy(self) -> None:
        """Test serializable_copy preserves WorkerState data without observer."""
        state = WorkerState(dummy_field="test_value")
        observer = MockObserver()
        state.observer(observer)

        copy = state.serializable_copy()

        assert isinstance(copy, WorkerState)
        assert copy.dummy_field == "test_value"
        assert copy._observer is None

    def test_worker_state_serialization(self) -> None:
        """Test WorkerState can be serialized via model_dump."""
        state = WorkerState(dummy_field="serialize_me")
        data = state.model_dump()

        assert data["dummy_field"] == "serialize_me"
        assert "__model__" in data

    def test_custom_state_with_multiple_fields(self) -> None:
        """Test custom state with multiple observable fields."""

        class TaskState(BaseState):
            task_name: str = "default_task"
            task_count: int = 0
            is_active: bool = False

        state = TaskState(task_name="test", task_count=5, is_active=True)
        assert state.task_name == "test"
        assert state.task_count == 5
        assert state.is_active is True

        # Test observer pattern with custom state
        observer = MockObserver()
        state.observer(observer)

        assert len(observer.notifications) == 1

    def test_notification_captures_state_snapshot(self) -> None:
        """Test notifications capture state at time of change, not live references."""
        state = WorkerState(dummy_field="snapshot1")
        observer = MockObserver()
        state.observer(observer)
        observer.notifications.clear()

        # Create first notification
        state.dummy_field = "snapshot2"
        state.notify_state_change()

        # Create second notification
        state.dummy_field = "snapshot3"
        state.notify_state_change()

        # First notification should still have snapshot2, not snapshot3
        assert observer.notifications[0].dummy_field == "snapshot2"
        assert observer.notifications[1].dummy_field == "snapshot3"

        # Changing state after notifications shouldn't affect them
        state.dummy_field = "snapshot4"
        assert observer.notifications[0].dummy_field == "snapshot2"
        assert observer.notifications[1].dummy_field == "snapshot3"


class TestBaselineStamping:
    """Test the _last_serialized baseline maintained by notify_state_change()."""

    def test_fresh_state_has_no_baseline(self) -> None:
        """A freshly constructed state has not published anything yet."""
        assert BaseState()._last_serialized is None
        assert WorkerState(dummy_field="x")._last_serialized is None

    def test_notify_state_change_stamps_baseline_without_observer(self) -> None:
        """The baseline is stamped unconditionally, even with no observer attached.

        A state mutated while detached and attached later must not arrive
        carrying a stale baseline, so the stamp has to read the state as it is
        at the moment of the call - hence the mutation before it.
        """
        state = WorkerState(dummy_field="detached")
        state.dummy_field = "mutated before the stamp"

        state.notify_state_change()

        assert state._last_serialized == state.model_dump_json()
        assert "mutated before the stamp" in str(state._last_serialized)

    def test_notify_state_change_still_notifies_and_stamps(self) -> None:
        """Notification behaviour is unchanged; the baseline is stamped as well."""
        state = WorkerState(dummy_field="v1")
        observer = RecordingObserver()
        state.observer(observer)
        observer.states.clear()

        state.dummy_field = "v2"
        state.notify_state_change()

        assert len(observer.states) == 1
        assert state._last_serialized == state.model_dump_json()


class TestNotifyIfChanged:
    """Test the notify_if_changed() checkpoint."""

    def test_mutation_then_checkpoint_notifies_once(self) -> None:
        """A dirty state notifies exactly once per checkpoint."""
        state = WorkerState(dummy_field="v1")
        observer = RecordingObserver()
        state.observer(observer)
        observer.states.clear()

        state.dummy_field = "v2"
        state.notify_if_changed()

        assert len(observer.states) == 1

    def test_two_checkpoints_without_mutation_notify_once(self) -> None:
        """The baseline moves on the first checkpoint, so the second is silent."""
        state = WorkerState(dummy_field="v1")
        observer = RecordingObserver()
        state.observer(observer)
        observer.states.clear()

        state.dummy_field = "v2"
        state.notify_if_changed()
        state.notify_if_changed()

        assert len(observer.states) == 1

    def test_explicit_notify_then_checkpoint_notifies_once(self) -> None:
        """An explicit notify followed by a checkpoint produces no duplicate."""
        state = WorkerState(dummy_field="v1")
        observer = RecordingObserver()
        state.observer(observer)
        observer.states.clear()

        state.dummy_field = "v2"
        state.notify_state_change()
        state.notify_if_changed()

        assert len(observer.states) == 1

    def test_checkpoint_without_observer_does_not_serialize(self) -> None:
        """The detached path returns before serializing - it must cost nothing.

        Base Akgent (and therefore Orchestrator, the busiest actor in the
        system) holds an unobserved BaseState, checkpointed once per message.
        """
        state = CountingState()
        state.value = "changed"

        state.notify_if_changed()

        assert state._dump_calls == 0

    def test_checkpoint_with_observer_serializes_exactly_twice(self) -> None:
        """Positive control for the counter, and the single-stamp-point guard.

        A dirty checkpoint serializes exactly twice: once to compare, once to
        re-stamp inside notify_state_change(). The second pass is bought
        knowingly - passing the already-computed JSON down to skip it would
        give the explicit and the automatic path two different stamp sites,
        which is the drift that keeps manual and automatic styles consistent.
        A bare ``> 0`` would stay green through that refactor; ``== 2`` does
        not, and it is also what makes the ``== 0`` assertion above mean
        "skipped" rather than "instrumentation broken".
        """
        state = CountingState()
        observer = RecordingObserver()
        state.observer(observer)
        observer.states.clear()
        state._dump_calls = 0

        state.value = "changed"
        state.notify_if_changed()

        assert state._dump_calls == 2
        assert len(observer.states) == 1

    def test_checkpoint_publishes_when_the_baseline_is_unset(self) -> None:
        """An unknown baseline must publish, never stay silent.

        observer() stamps on attach, so a state cannot reach this shape
        through the public attach path today - it takes assigning the observer
        directly. The fail-safe direction still has to be pinned: an
        "optimisation" that treated a None baseline as "nothing to compare, so
        nothing to send" would pass every other test here and drop the very
        first snapshot. PersistenceSubscriber upserts a latest-per-agent row
        rather than appending an event, so a first snapshot that is never sent
        is never recoverable.
        """
        state = WorkerState(dummy_field="never published")
        observer = RecordingObserver()
        state._observer = observer
        assert state._last_serialized is None

        state.notify_if_changed()

        assert len(observer.states) == 1


class TestDeepMutationDetection:
    """Mutations *inside* fields must be detected - the reason for the digest design.

    Each mutation shape is an independent claim about the design, so the three
    live as separate tests rather than one parametrized case: a partial
    implementation must not be able to pass by satisfying only one of them.

    Each also checkpoints a second time and asserts silence: a deep mutation
    must move the baseline, not just fire once. A stamp taken from a stale
    snapshot would notify on every later checkpoint forever - an upsert per
    turn, for the rest of the team's life.
    """

    def test_list_append_is_detected(self) -> None:
        """state.items.append(x) notifies, once."""
        state = DeepState()
        observer = RecordingObserver()
        state.observer(observer)
        observer.states.clear()

        state.items.append("first")
        state.notify_if_changed()

        assert len(observer.states) == 1

        state.notify_if_changed()

        assert len(observer.states) == 1

    def test_dict_assignment_is_detected(self) -> None:
        """state.by_id[k] = v notifies, once."""
        state = DeepState()
        observer = RecordingObserver()
        state.observer(observer)
        observer.states.clear()

        state.by_id["a"] = 1
        state.notify_if_changed()

        assert len(observer.states) == 1

        state.notify_if_changed()

        assert len(observer.states) == 1

    def test_nested_model_field_rebinding_is_detected(self) -> None:
        """state.nested.field = v notifies, once."""
        state = DeepState()
        observer = RecordingObserver()
        state.observer(observer)
        observer.states.clear()

        state.nested.field = "updated"
        state.notify_if_changed()

        assert len(observer.states) == 1

        state.notify_if_changed()

        assert len(observer.states) == 1


class TestAttachTimeSemantics:
    """Test that observer() keeps notifying at attach time and leaves a fresh baseline."""

    def test_attach_notifies_once_and_stamps_baseline(self) -> None:
        """An agent whose state never changes still seeds exactly one notification."""
        state = WorkerState(dummy_field="initial")
        observer = RecordingObserver()

        state.observer(observer)

        assert len(observer.states) == 1
        assert state._last_serialized is not None

    def test_mutation_while_detached_is_published_at_attach_time(self) -> None:
        """Attaching publishes current content, so the next checkpoint is silent."""
        state = WorkerState(dummy_field="initial")
        state.dummy_field = "mutated while detached"
        observer = RecordingObserver()

        state.observer(observer)
        assert len(observer.states) == 1

        state.notify_if_changed()

        assert len(observer.states) == 1


class TestBaselinePrivacy:
    """The baseline is private state and must never reach the wire."""

    def test_baseline_absent_from_serialization(self) -> None:
        """_last_serialized appears in neither model_dump() nor model_dump_json()."""
        state = WorkerState(dummy_field="value")
        state.observer(RecordingObserver())
        assert state._last_serialized is not None

        assert "_last_serialized" not in state.model_dump()
        assert "_last_serialized" not in state.model_dump_json()

    def test_serializable_copy_drops_the_baseline(self) -> None:
        """The copy is born without a baseline and never serializes one."""
        state = WorkerState(dummy_field="value")
        state.observer(RecordingObserver())

        copy = state.serializable_copy()

        assert copy._last_serialized is None
        assert "_last_serialized" not in copy.model_dump()
        assert "_last_serialized" not in copy.model_dump_json()
