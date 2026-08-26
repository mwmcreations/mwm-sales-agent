#!/usr/bin/env python3
"""
burst.py — PATCH #96. One reply per burst, not one reply per fragment.

WHAT WENT WRONG
---------------
People do not type one tidy message. They type in bursts:

    "Hello"
    "Are you guys available for a tour today?"

Each fragment arrives as its own webhook and each one starts its own
generation, so Jaysee Soto got SIX replies to six fragments on 26 Aug 2026 —
including two different greetings and two different phrasings of "Are you the
owner of the practice?".

The expensive one was the third pair. He wrote "Yes", then "Looking to go this
afternoon around 230". The reply to "Yes" said **"Today is fully booked"** and
offered Friday. The reply to the second said **"Michael's available today at
2:30 PM!"**. Both reached him, seconds apart, contradicting each other.

THE FIX, AND WHY IT IS THIS ONE
-------------------------------
The obvious approach is to wait a few seconds and merge. That would mean
sleeping inside the WhatsApp webhook, and this webhook has NO message-id
idempotency — a Meta retry is already processed twice, and adding a sleep makes
retries far more likely. A debounce would have bought a duplicate-reply bug to
fix a duplicate-reply bug.

So this suppresses the STALE reply instead of delaying the fresh one:

    · every inbound takes a sequence number for its sender
    · just before a reply is sent, we ask whether a NEWER inbound has arrived
      from that sender while we were generating
    · if it has, this reply is dropped — the newer generation is already
      running, it has the earlier message in its history, and it will answer

No added latency, no sleep, no retry exposure. A reply is only ever dropped
when we can point at the newer message that supersedes it.

FAILING SAFE
------------
· `is_superseded` returns False on anything it does not understand. A lead who
  gets an extra message is mildly annoyed; a lead who gets silence is lost.
· A newer message older than MAX_SUPERSEDE_AGE_S never suppresses anything, so
  a stale sequence number from an hour ago cannot silence a live reply.
"""

import os
import threading
import time

# How recent the superseding message must be for us to trust that its own
# generation is still in flight and will answer.
MAX_SUPERSEDE_AGE_S = float(os.getenv("MAYA_MAX_SUPERSEDE_AGE_S", "120"))

_LOCK = threading.Lock()
_SEQ = {}      # sender -> latest sequence number
_STAMP = {}    # sender -> epoch of that latest inbound
_MAX_SENDERS = 5000


def _prune_locked():
    """Keep the maps bounded without touching anything recent."""
    if len(_SEQ) <= _MAX_SENDERS:
        return
    cutoff = time.time() - 86400
    for k in [k for k, t in _STAMP.items() if t < cutoff]:
        _SEQ.pop(k, None)
        _STAMP.pop(k, None)


def note_inbound(sender, now=None):
    """Record an inbound and return its sequence number for this sender."""
    if not sender:
        return None
    if now is None:
        now = time.time()
    with _LOCK:
        seq = _SEQ.get(sender, 0) + 1
        _SEQ[sender] = seq
        _STAMP[sender] = float(now)
        _prune_locked()
        return seq


def latest(sender):
    """(sequence, epoch) of the most recent inbound seen for `sender`."""
    with _LOCK:
        return _SEQ.get(sender), _STAMP.get(sender)


def is_superseded(sender, seq, now=None, max_age_s=None):
    """
    True when a NEWER inbound from `sender` arrived recently enough that its own
    reply is still coming. Anything uncertain returns False — never go silent on
    a guess.
    """
    if not sender or seq is None:
        return False
    if now is None:
        now = time.time()
    if max_age_s is None:
        max_age_s = MAX_SUPERSEDE_AGE_S
    with _LOCK:
        newest = _SEQ.get(sender)
        stamp = _STAMP.get(sender)
    if newest is None or stamp is None:
        return False
    try:
        if newest <= seq:
            return False
        return (float(now) - float(stamp)) <= float(max_age_s)
    except (TypeError, ValueError):
        return False


def reset(sender=None):
    """Test helper. Clears one sender, or everything."""
    with _LOCK:
        if sender is None:
            _SEQ.clear()
            _STAMP.clear()
        else:
            _SEQ.pop(sender, None)
            _STAMP.pop(sender, None)
