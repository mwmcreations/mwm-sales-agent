#!/usr/bin/env python3
"""test_studio_portal_reasons.py — S29. The portal knew why and would not say.

HIS Agents paid $1,400 on 5 Aug for four hours. On 24 Aug Gema Hiatt wrote:
"I went into our portal to try and book our session, but nothing is available
at all." Her record was FINE — Aug 5 to Sep 4, 0.0/4.0 used, Active.

The handler has FOUR ways to return an empty day and it labels every one of
them: out_of_range, contract_expired, no_hours, availability_unavailable.
The front end handled ONE. The other three fell through to:

    "No available times on this date — try another day."

which is false for all three. A client shopping dates at and past her contract
end was told, on every attempt, to try another day — by a system that had
already decided no other day would ever work. She stopped, and the only reason
we found out is that she happened to email.

Nothing alerted either. When the calendar feed dies we get an email; when a
paying client is refused every slot, nothing fired at all. Same shape as the
Sheets 403 the same week: it fails in the direction of silence.

§3 is the one that matters — the operator notice — because the message on the
screen only helps the client who is still trying.

Run: python3 test_studio_portal_reasons.py
"""

import re
import sys

SRC = open("wordpress/mwm-studio-booking.php").read()

import re

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


def block(start, end):
    i = SRC.index(start)
    return SRC[i:SRC.index(end, i + len(start))]


# ── §1 · the server still labels every refusal, and now carries the limit ────
handler = block("public function mwm_studio_get_available_slots()", "public function mwm_studio_create_booking()")
for r in ("out_of_range", "contract_expired", "no_hours", "availability_unavailable"):
    ok("'reason'   => '%s'" % r in handler
       or "'reason'       => '%s'" % r in handler
       or "'reason'    => '%s'" % r in handler
       or "'reason' => '%s'" % r in handler,
       "handler still returns reason=%s" % r)

ok("'max_date' => $max_date" in handler,
   "out_of_range now carries the date the client must book by")
ok("'kind'     => $oor_kind" in handler,
   "and distinguishes a past date from one after the contract end")
ok("'contract_end' => $client->contract_end_date" in handler,
   "contract_expired carries the end date")
ok("'remaining' => $remaining" in handler,
   "no_hours carries what is left")

# ── §2 · the client is told which of the four happened ──────────────────────
js = block("loadSlots: function(date)", "confirmBooking: function()")
ok("reason === 'availability_unavailable'" in js, "feed-down message kept")
ok("reason === 'out_of_range'" in js, "out_of_range now has its own message")
ok("reason === 'contract_expired'" in js, "contract_expired now has its own message")
ok("reason === 'no_hours'" in js, "no_hours now has its own message")
ok("Your hours must be used by" in js,
   "the out_of_range message names the deadline instead of 'try another day'")
ok("(813) 503-1224" in js,
   "and every dead end offers a human — a client who cannot book must not be left with a shrug")

_generic = "No available times on this date"
# Count it in CODE only. The patch's own comment quotes the old string to explain
# what it replaced, and an assertion that counts a comment is measuring the wrong
# thing — this suite has been bitten by that before.
_js_code = "\n".join(l for l in js.split("\n") if not l.strip().startswith("//"))
ok(_js_code.count(_generic) == 1,
   "the generic line survives for the ONE case where it is true: a genuinely busy day")
ok(js.count(_generic) == 2,
   "and the comment above it still quotes the string it replaced, so the next reader "
   "knows what this branch is for")
for r in ("out_of_range", "contract_expired", "no_hours"):
    seg = js[js.index("reason === '%s'" % r):]
    ok(seg.index("return;") < seg.find(_generic) if _generic in seg else True,
       "%s returns before it can fall through to the generic line" % r)

ok("fmtDate: function(iso)" in js or "fmtDate: function(iso)" in SRC,
   "a date formatter exists for those messages")
ok(SRC.index("fmtDate: function(iso)") < SRC.index("loadSlots: function(date)"),
   "fmtDate is defined before loadSlots uses it")

# ── §3 · THE ONE THAT MATTERS · silence is the actual defect ────────────────
ok("private function notice_client_blocked(" in SRC,
   "a structural refusal now raises an operator notice")
notice = block("private function notice_client_blocked(", "/** S15: throttled")
ok("get_transient( $key )" in notice and "set_transient( $key, 1, DAY_IN_SECONDS )" in notice,
   "throttled once per client per reason per day — a refused client must not become an alert storm")
ok("$client->email" in notice, "the notice names WHO cannot book")
ok("empty( $client->id )" in notice,
   "and it is safe when there is no client on the request")

for r in ("out_of_range", "contract_expired", "no_hours"):
    ok("notice_client_blocked( $client, '%s'" % r in handler,
       "%s fires the notice" % r)

_past = handler[handler.index("$oor_kind = "):handler.index("'reason'   => 'out_of_range'")]
ok("'after_contract_end' === $oor_kind" in _past,
   "a date in the PAST does not alert — that is the client mis-clicking, not our bug")

# ── §4 · provenance ─────────────────────────────────────────────────────────
# Pin the MINIMUM, not the exact string. The exact pin failed the whole gate
# the moment 2.8.2 shipped the am/pm fix — a test that breaks on every release
# stops being read. What matters is that the file was versioned at all and did
# not go backwards past the release this test was written for.
_ver = re.search(r"Version:\s*(\d+)\.(\d+)\.(\d+)", SRC)
ok(_ver is not None, "the plugin declares a version")
ok(_ver is not None and tuple(int(x) for x in _ver.groups()) >= (2, 8, 1),
   "plugin version is 2.8.1 or newer (currently %s)"
   % (_ver.group(0) if _ver else "absent"))
ok("MWM_STUDIO_VERSION', '2.8.1'" in SRC, "and the constant matches the header")
ok(SRC.count("{") == SRC.count("}"), "braces balance")
ok(SRC.count("(") == SRC.count(")"), "parens balance")

print("\nS29_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))

print("\n" + "=" * 62)
print("  STUDIO PORTAL REFUSAL REASONS (S29): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
