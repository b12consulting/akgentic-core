"""``is_alive()`` answers for a deallocated actor, not only a stopped one.

Pykka's ``ActorRef.is_alive()`` is ``not actor_stopped.is_set()``. An actor that
is garbage-collected without ever being stopped never sets that flag, so the ref
reports **alive** while every call through it fails — and ``tell`` happily drops
messages into an inbox nobody drains.

``ActorAddressImpl`` has always documented the opposite ("a torn-down or
collected ref is simply 'not alive'"); it just delegated to Pykka and inherited
the gap. These tests pin the documented behaviour, because the caller that
matters — a timer thread polling liveness to decide whether to give up — never
gives up while the answer is wrong.
"""

from __future__ import annotations

import gc
import weakref

import pytest
from pykka import ActorDeadError

from akgentic.core.actor_address_impl import ActorAddressImpl
from akgentic.core.agent import Akgent
from akgentic.core.agent_config import BaseConfig


class _Probe(Akgent[BaseConfig, None]):
    """Minimal actor; started only where a live mailbox is needed."""


def _address_of_collected_actor() -> ActorAddressImpl:
    """Build an address, then let its actor be collected without stopping it."""
    actor = _Probe(config=BaseConfig(name="probe", role="tester"))
    address = ActorAddressImpl(actor.actor_ref)
    ref = weakref.ref(actor)
    del actor
    gc.collect()
    assert ref() is None, "the actor must actually be collected for this to test anything"
    return address


class TestCollectedActor:
    """A deallocated actor is not alive, and refuses delivery."""

    def test_is_alive_is_false_once_the_actor_is_collected(self) -> None:
        """The regression: this returned True, so pollers never stopped polling."""
        assert _address_of_collected_actor().is_alive() is False

    def test_pykka_still_reports_it_alive(self) -> None:
        """Why the check cannot simply delegate — the gap is in Pykka's semantics.

        Asserted so that a future Pykka release closing this gap shows up here as
        a failing test rather than as silently redundant code.
        """
        address = _address_of_collected_actor()

        assert address._actor_ref.is_alive() is True
        assert address.is_alive() is False

    def test_tell_refuses_rather_than_filling_an_unread_inbox(self) -> None:
        """Pykka's own ``tell`` would accept this message and drop it on the floor."""
        with pytest.raises(ActorDeadError):
            _address_of_collected_actor().tell("into the void")

    def test_ask_refuses_rather_than_blocking_forever(self) -> None:
        """No handler will ever run, so the reply would never arrive."""
        with pytest.raises(ActorDeadError):
            _address_of_collected_actor().ask("into the void", timeout=0.1)


class TestStoppedActor:
    """The case Pykka already handled stays handled, and reports the same error."""

    def test_is_alive_is_false_after_stop(self) -> None:
        actor_ref = _Probe.start(config=BaseConfig(name="probe", role="tester"))
        address = ActorAddressImpl(actor_ref)
        actor_ref.stop()

        assert address.is_alive() is False

    def test_tell_raises_the_same_error_as_the_collected_case(self) -> None:
        """One exception type for both deaths — callers need a single ``except``."""
        actor_ref = _Probe.start(config=BaseConfig(name="probe", role="tester"))
        address = ActorAddressImpl(actor_ref)
        actor_ref.stop()

        with pytest.raises(ActorDeadError):
            address.tell("too late")


class TestLiveActor:
    """The fix must not make a live actor look dead."""

    def test_a_live_actor_is_alive_and_accepts_delivery(self) -> None:
        actor_ref = _Probe.start(config=BaseConfig(name="probe", role="tester"))
        address = ActorAddressImpl(actor_ref)
        try:
            assert address.is_alive() is True
            address.tell("hello")  # must not raise
        finally:
            actor_ref.stop()
