#!/usr/bin/env python3
"""
test_burst.py — PATCH #96.

Jaysee Soto, 26 Aug 2026: six fragments, six replies, two of them
contradicting each other in front of a lead who was trying to book.

The rule under test is deliberately one-sided. Dropping a reply when we can
point at the newer message that supersedes it is safe. Dropping one on a guess
means silence, and silence loses the lead. Every uncertain path must return
False.

Run: python3 test_burst.py
"""
import sys
import threading

import burst as B

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


def fresh(name):
    B.reset()
    return name


# ── §1 · THE REGRESSION — "Yes" then "around 230", six seconds apart ────────
s = fresh("whatsapp:+13059673476")
seq_yes = B.note_inbound(s, now=1000.0)          # "Yes"
seq_230 = B.note_inbound(s, now=1006.0)          # "Looking to go this afternoon around 230"

ok(B.is_superseded(s, seq_yes, now=1010.0) is True,
   "the reply to 'Yes' is stale — this is the 'Today is fully booked' message")
ok(B.is_superseded(s, seq_230, now=1010.0) is False,
   "the reply to the newer message still goes out — the lead is not left silent")

# ── §2 · one reply survives a burst of any size ────────────────────────────
s = fresh("w:burst")
seqs = [B.note_inbound(s, now=1000.0 + i) for i in range(6)]
survivors = [q for q in seqs if not B.is_superseded(s, q, now=1010.0)]
ok(len(survivors) == 1, "exactly one of six fragments replies: %d" % len(survivors))
ok(survivors[0] == seqs[-1], "and it is the last one, which has the whole thought")

# ── §3 · the ordinary case is untouched ────────────────────────────────────
s = fresh("w:single")
q = B.note_inbound(s, now=2000.0)
ok(B.is_superseded(s, q, now=2001.0) is False, "a lone message always replies")
ok(B.is_superseded(s, q, now=2600.0) is False, "even after a slow generation")

s2 = fresh("w:a")
qa = B.note_inbound("w:a", now=3000.0)
B.note_inbound("w:b", now=3001.0)
ok(B.is_superseded("w:a", qa, now=3002.0) is False,
   "another LEAD's message never suppresses this one")

# ── §4 · every uncertain path fails OPEN ───────────────────────────────────
B.reset()
ok(B.is_superseded("w:never-seen", 5, now=1.0) is False,
   "an unknown sender never suppresses — silence is the worse failure")
ok(B.is_superseded(None, 1) is False, "no sender, no suppression")
ok(B.is_superseded("w:x", None) is False, "no sequence, no suppression")
ok(B.note_inbound(None) is None, "an empty sender takes no sequence number")
ok(B.is_superseded("w:x", "not-a-number", now=1.0) is False,
   "a junk sequence never suppresses")

s = fresh("w:stale")
old = B.note_inbound(s, now=1000.0)
B.note_inbound(s, now=1005.0)
ok(B.is_superseded(s, old, now=1005.0 + B.MAX_SUPERSEDE_AGE_S + 1) is False,
   "a superseding message too old to still be generating cannot silence us")
ok(B.is_superseded(s, old, now=1005.0 + B.MAX_SUPERSEDE_AGE_S - 1) is True,
   "but one inside the window can")
ok(B.is_superseded(s, old, now=1006.0, max_age_s=0.5) is False,
   "the window is tunable")

# ── §5 · sequence numbers are per sender, monotonic, and thread-safe ───────
B.reset()
ok(B.note_inbound("w:m", now=1.0) == 1 and B.note_inbound("w:m", now=2.0) == 2,
   "sequences count up per sender")
ok(B.note_inbound("w:other", now=3.0) == 1, "and start at 1 for a new sender")
ok(B.latest("w:m")[0] == 2, "latest() reports the newest sequence")
ok(B.latest("w:never")[0] is None, "and None for a sender we have not seen")

B.reset()
errs = []


def hammer():
    try:
        for _ in range(200):
            B.note_inbound("w:race")
    except Exception as e:      # pragma: no cover
        errs.append(e)


ts = [threading.Thread(target=hammer) for _ in range(8)]
[t.start() for t in ts]
[t.join() for t in ts]
ok(not errs, "concurrent inbounds do not raise: %s" % errs[:1])
ok(B.latest("w:race")[0] == 1600,
   "and no sequence number is lost to a race: %s" % (B.latest("w:race")[0],))

ok(B.is_superseded("w:race", 1599) is True, "the second-to-last is superseded")
ok(B.is_superseded("w:race", 1600) is False, "the last still replies")

print("\nPATCH96_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  BURST (Patch #96): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
