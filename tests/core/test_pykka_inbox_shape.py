"""Pin the Pykka inbox internals that ``Akgent.consume_mailbox`` reaches into.

``consume_mailbox`` removes entries from ``actor_ref.actor_inbox.queue`` while
holding ``actor_inbox.mutex``, and relies on ``deque.remove`` matching envelopes
by identity. None of that is Pykka's public API — it is the acknowledged cost of
being able to purge a mailbox at all — so this test asserts the shape directly.
A Pykka upgrade that changes it fails here, loudly, instead of silently breaking
mailbox purging in production.

The probe is a bare ``pykka.ThreadingActor``, not an ``Akgent``: the subject is
the Pykka invariant itself, not akgentic-core semantics. Same precedent as
``test_pykka_mailbox_drain_on_self_stop.py``.
"""

from __future__ import annotations

import queue
import threading
from collections import deque
from collections.abc import Generator
from typing import Any

import pykka
import pytest
from pykka._envelope import Envelope

TIMEOUT = 5.0


@pytest.fixture(autouse=True)
def cleanup_actors() -> Generator[None, None, None]:
    """Stop any leaked probe actors after each test so failures don't cascade."""
    yield
    pykka.ActorRegistry.stop_all()


class _ParkedProbe(pykka.ThreadingActor):
    """Actor that parks inside a handler, so mail piles up unread behind it."""

    def __init__(self, parked: threading.Event, release: threading.Event) -> None:
        super().__init__()
        self.parked = parked
        self.release = release

    def on_receive(self, message: Any) -> str:
        if message == "park":
            self.parked.set()
            self.release.wait(timeout=TIMEOUT)
        return "ok"


def test_actor_inbox_is_a_queue_of_envelopes_with_a_mutex_and_a_deque() -> None:
    """The inbox exposes ``.mutex`` and a ``deque`` at ``.queue`` holding ``Envelope``s.

    Both an unread ``tell`` and an unread ``ask`` are queued, so the assertion also
    pins the ``reply_to`` distinction ``consume_mailbox`` uses to leave a blocked
    asker's message alone.
    """
    parked, release = threading.Event(), threading.Event()
    actor_ref = _ParkedProbe.start(parked, release)
    try:
        actor_ref.tell("park")
        assert parked.wait(timeout=TIMEOUT), "probe never entered the park handler"

        actor_ref.tell("told")
        asked = actor_ref.ask("asked", block=False)

        inbox = actor_ref.actor_inbox
        assert isinstance(inbox, queue.Queue)
        assert isinstance(inbox.queue, deque)

        # Acquiring it as a context manager is the same use consume_mailbox makes.
        with inbox.mutex:
            envelopes = list(inbox.queue)

        assert [type(envelope) for envelope in envelopes] == [Envelope, Envelope]
        assert [envelope.message for envelope in envelopes] == ["told", "asked"]
        assert envelopes[0].reply_to is None, "tell must queue an envelope with no reply_to"
        assert envelopes[1].reply_to is not None, "ask must queue an envelope carrying a reply_to"
    finally:
        release.set()

    assert asked.get(timeout=TIMEOUT) == "ok"


def test_envelope_has_no_equality_so_removal_matches_by_identity() -> None:
    """``deque.remove`` must match the exact envelope, never an equal-looking one.

    ``consume_mailbox`` collects the envelopes to drop and then removes them by
    value. If ``Envelope`` ever gained an ``__eq__``, ``remove`` would start
    matching the *first* equal entry instead of the one collected, and a duplicate
    payload in the mailbox would see the wrong copy removed.
    """
    assert Envelope.__eq__ is object.__eq__

    first = Envelope("same")
    second = Envelope("same")
    pending = deque([first, second])

    pending.remove(second)

    assert list(pending) == [first]
