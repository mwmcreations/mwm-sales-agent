#!/usr/bin/env python3
"""test_info_inbox.py — the watcher on info@mwmcreations.com.

THE EMAIL THAT CAUSED THIS: a lead wrote to info@ asking to change his studio
visit. Michael found it by luck, having opened a mailbox he does not normally
open. "Those kind of emails can be there for days without me looking at it."

§1 is that exact email, and it MUST come out `urgent`. It did not, first
attempt: the pattern wanted "change my visit" adjacent and he had written
"change my studio VISIT". A classifier tuned so tightly that it misses the one
message it was built for is worse than no classifier, because it would be
trusted.

§3 is the asymmetry that governs every rule here. A missed lead costs a
booking. A false alert costs one line in Slack. When unsure, ALERT.

§5 guards the thing that makes this safe to point at a live client mailbox:
it can only read. A reader that returns nothing is an annoyance; one that
marks mail read, archives it or replies is a business incident.

Run: python3 test_info_inbox.py
"""

import io
import sys

import info_inbox as ii

_passed = _failed = 0
_FAILS = []


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print("  PASS  " + label)
    else:
        _failed += 1
        _FAILS.append(label)
        print("  FAIL  %s\n          got=%r want=%r" % (label, got, want))


def ok(label, cond):
    check(label, bool(cond), True)


def pri(sender, subject, snippet=""):
    return ii.classify(sender, subject, snippet)[0]


print("\n=== 1. THE FOUNDING EMAIL — this one is not allowed to be missed ===")
check("'change my studio visit' is URGENT",
      pri("Todd <myorlandosold@gmail.com>", "Need to change my studio visit"),
      ii.PRIORITY_URGENT)
# the near-misses that broke the first version
for subj in ["Can we move our Thursday session?",
             "I need to switch my shoot to next week",
             "Please push the recording to Friday",
             "change the appointment please",
             "Reschedule request",
             "rescheduling my visit",
             "I have to cancel the podcast recording",
             "Cancelling tomorrow, sorry",
             "Running late for tomorrow",
             "I can't make it on Thursday",
             "we won't make it",
             "This is urgent",
             "Need a refund",
             "I want to complain about the edit"]:
    check("URGENT: %s" % subj[:42], pri("A <a@client.com>", subj),
          ii.PRIORITY_URGENT)

print("\n=== 2. leads, and people who are merely people ===")
for subj in ["Question about pricing", "What is your hourly rate?",
             "Interested in booking a studio session", "Do you have availability?",
             "How much for a podcast shoot?", "Requesting a quote"]:
    check("LEAD: %s" % subj[:42], pri("B <b@client.com>", subj), ii.PRIORITY_LEAD)

for subj in ["Hello", "Thanks for yesterday!", "Following up", "Quick question",
             "(no subject)", ""]:
    check("HUMAN: %r" % subj[:30], pri("C <c@client.com>", subj), ii.PRIORITY_HUMAN)

print("\n=== 3. the asymmetry — when unsure, ALERT ===")
ok("an empty subject from a stranger still reaches a human",
   ii.needs_attention(pri("stranger@nowhere.io", "")))
ok("gibberish still reaches a human",
   ii.needs_attention(pri("x <x@y.zz>", "asdkjh")))
ok("a non-English subject still reaches a human",
   ii.needs_attention(pri("Cristina <c@enlid.com.br>", "Sobre o contrato")))
ok("urgent outranks lead when both words appear",
   pri("A <a@b.com>", "Booking question - need to cancel") == ii.PRIORITY_URGENT)
check("priority ordering puts urgent first",
      sorted([ii.PRIORITY_HUMAN, ii.PRIORITY_URGENT, ii.PRIORITY_LEAD],
             key=lambda p: ii.PRIORITY_ORDER[p]),
      [ii.PRIORITY_URGENT, ii.PRIORITY_LEAD, ii.PRIORITY_HUMAN])

print("\n=== 4. the robots that really land in this mailbox ===")
# Every one of these was pulled from the live account, not invented.
REAL_NOISE = [
    ("info@dsbackend.com", "[MWM Screens] 1 of your players has been offline for some time."),
    ("Stripe <no-reply@stripe.com>", "Payment of $349.00 from Timothy T Berger"),
    ("support@twilio.zendesk.com", "Request #29054838 | 1. whatsapp:+13186678208"),
    ("Railway <no-reply@railway.app>", "Security patch scheduled: Postgres"),
    ("WordPress <wordpress@mwmcreations.com>", "[] Your site has updated to WordPress 7.1"),
    ("Google <no-reply@accounts.google.com>", "Security alert"),
    ("noreply@indeed.com", "1 new videographer job in Orlando, FL"),
]
for s, subj in REAL_NOISE:
    check("IGNORE: %s" % subj[:44], pri(s, subj), ii.PRIORITY_IGNORE)

print("\n=== 5. our own people are not clients ===")
for a in ["michael@mwmcreations.com", "Michael <michael@mwmcreations.com>",
          "lara@mwmcreations.com", "someone@mwmscreens.com", "x@mwmfilms.tv"]:
    check("internal: %s" % a[:38], pri(a, "Need to cancel everything"),
          ii.PRIORITY_IGNORE)
ok("a lookalike domain is NOT treated as internal",
   pri("scam@mwmcreations.com.evil.ru", "cancel") != ii.PRIORITY_IGNORE)
check("address extraction from a full From header",
      ii._address_of("Todd Berger <MyOrlandoSold@Gmail.com>"),
      "myorlandosold@gmail.com")
check("...and from a bare address", ii._address_of("a@b.com"), "a@b.com")

print("\n=== 6. READ-ONLY IS STRUCTURAL — it points at a live client mailbox ===")
SRC = io.open("info_inbox.py", encoding="utf-8").read()
CODE = "\n".join(l for l in SRC.split("\n") if not l.strip().startswith("#"))
for verb in ("modify", "trash", "batchModify", "send", "delete", "insert", "import_"):
    ok("no users().messages().%s( call" % verb,
       (".%s(" % verb) not in CODE.replace("re.", "").replace("_re.", ""))
ok("fetches are METADATA only — cannot mark read, keeps bodies out of logs",
   'format="metadata"' in CODE)
# NOTE: this line was first written as `'format="full"' in CODE is False`,
# which Python reads as a CHAINED comparison — (x in CODE) and (CODE is False)
# — and so it failed for a reason unrelated to its label. Third time this
# session a test has been wrong rather than the code. Written plainly now.
ok("...and never format=full", 'format="full"' not in CODE)
ok("the classifier is pure — no service object reaches it",
   "service" not in SRC.split("def classify")[1].split("\ndef ")[0])

print("\n=== 7. triage + rendering ===")
BATCH = [
    {"id": "1", "from": "C <c@x.com>", "subject": "Hello", "snippet": "", "date": "b"},
    {"id": "2", "from": "A <a@x.com>", "subject": "cancel my session", "snippet": "", "date": "a"},
    {"id": "3", "from": "no-reply@stripe.com", "subject": "Payment of $1", "snippet": "", "date": "c"},
    {"id": "4", "from": "B <b@x.com>", "subject": "pricing?", "snippet": "", "date": "d"},
]
rows = ii.triage(BATCH)
check("worst first", [r["priority"] for r in rows],
      [ii.PRIORITY_URGENT, ii.PRIORITY_LEAD, ii.PRIORITY_HUMAN, ii.PRIORITY_IGNORE])
ok("every row carries a reason a human can read", all(r["why"] for r in rows))
ok("triage does not mutate its input", BATCH[0].get("priority") is None)
check("an empty batch", ii.triage([]), [])
check("None", ii.triage(None), [])
d = ii.describe(rows[0])
ok("the urgent badge is unmissable", "NEEDS A REPLY NOW" in d)
ok("...and names the sender and subject", "a@x.com" in d and "cancel my session" in d)

print("\n=== 8. failures must be told apart — the remedies share nothing ===")
check("unauthorized_client is a SCOPE problem",
      ii.diagnose(Exception("unauthorized_client: Client is unauthorized"))[0],
      ii.ERR_SCOPE)
ok("...and the message names the trap that cost us twice",
   "two different things" in ii.diagnose(Exception("unauthorized_client"))[1])
check("Precondition check failed is an IMPERSONATION problem",
      ii.diagnose(Exception("Precondition check failed."))[0], ii.ERR_IMPERSONATION)
ok("...and says the address must be a real user, not a group",
   "not a group" in ii.diagnose(Exception("Precondition check failed."))[1])
check("anything else is unknown, not swallowed",
      ii.diagnose(ValueError("weird"))[0], ii.ERR_UNKNOWN)

print("\n=== 9. the watcher loop, read off app.py ===")
APP = io.open("app.py", encoding="utf-8").read()
W = APP.split("def _info_watch_once")[1].split("def _info_watch_thread")[0]
ok("the FIRST run is calibration only — it does not stampede a backlog",
   "_INFO_CALIBRATED" in W and "No alerts sent" in W)
ok("...and marks the backlog seen so it never re-fires", "_info_mark_seen" in W)
ok("a failed post is NOT marked seen — it retries next pass",
   "must be retried" in W)
ok("failure is reported on the TRANSITION, not every 5 minutes",
   "_INFO_WATCH_OK[0] is not False" in W)
ok("recovery is announced too", "is back" in W)
ok("the down-alert explains it looks like a quiet inbox", "quiet inbox" in W)
ok("seen-state is pg-backed, not an in-memory set that a deploy re-arms",
   "pg_store" in APP.split("def _info_seen_before")[1].split("\ndef ")[0])
ok("polls every 5 minutes — a waiting client is time-sensitive",
   "_t.sleep(300)" in APP.split("def _info_watch_thread")[1].split("threading.Thread")[0])
ok("it has a heartbeat, so a dead thread is visible in /health",
   '_heartbeat("info_inbox_watch")' in APP)
ok("GMAIL_SCOPES now actually asks for readonly",
   "gmail.readonly" in APP.split("GMAIL_SCOPES =")[1].split("]")[0])
ok("...and still asks for send, so nothing existing breaks",
   "gmail.send" in APP.split("GMAIL_SCOPES =")[1].split("]")[0])

print("\n=== 10. CALIBRATED against the real mailbox, 21 Aug first run ===")
# These are the actual messages the watcher read on its first live pass. The
# first version scored Whitney's acknowledgement as URGENT because the word
# "postponed" was in the Re: subject — and that subject was MICHAEL'S wording,
# echoed back. On a reply, the subject is our words; only the snippet is the
# client's. That distinction is the whole of this section.
REAL = [
  # sender, subject, snippet, expected
  ("Chef Whitney Aronoff <whitney.aronoff@gmail.com>",
   "Re: Thursday is postponed — please stand down",
   "Noted. Thank you! Whitney C. Aronoff", ii.PRIORITY_HUMAN),
  ("Luiz Bolfer <drbolfer@gmail.com>",
   "Re: Confirming your session — Saturday, August 15",
   "I need to cancel, something came up", ii.PRIORITY_URGENT),
  ("marc holmes <mhholmes2000@gmail.com>",
   "Re: Confirming your session — Tuesday, August 25",
   "Yes see you then", ii.PRIORITY_HUMAN),
  ("Anika Patel <anika.patel@frenchiesnails.com>",
   "Re: Confirming your session — Tuesday, August 18",
   "Thank you so much", ii.PRIORITY_HUMAN),
  ("Jonathan Pineda <john.pineda@fidelityfl.com>",
   "Re: Confirming your session — Thursday, August 13",
   "Confirmed, thanks", ii.PRIORITY_HUMAN),
  ("MWM Screens <info@dsbackend.com>",
   "[MWM Screens] 1 of your players has been offline for some time.",
   "Hello Michael", ii.PRIORITY_IGNORE),
  ("Michael Moraes <michael@mwmcreations.com>",
   "Thursday is postponed — please stand down", "", ii.PRIORITY_IGNORE),
  ("Berkay Cansu SANDAL via TestFlight <testflight@email.apple.com>",
   "Berkay Cansu SANDAL has invited you to test OpenAI Ads.",
   "", ii.PRIORITY_IGNORE),
]
for sender, subj, snip, want in REAL:
    check("real: %-34s -> %s" % (subj[:34], want),
          pri(sender, subj, snip), want)

ok("an acknowledgement is NOT an emergency",
   pri("W <w@x.com>", "Re: your session is cancelled", "Ok, understood") != ii.PRIORITY_URGENT)
ok("...but the same words FROM the client still are",
   pri("W <w@x.com>", "Re: your session", "I need to cancel") == ii.PRIORITY_URGENT)
ok("a FRESH (non-reply) subject still triggers on the subject alone",
   pri("W <w@x.com>", "Cancelling my booking", "") == ii.PRIORITY_URGENT)
ok("Fwd: is treated like Re: — also not the client's words",
   pri("W <w@x.com>", "Fwd: cancellation notice", "fyi") != ii.PRIORITY_URGENT)
ok("every real client in that batch still reaches a human",
   all(ii.needs_attention(pri(s, su, sn))
       for s, su, sn, w in REAL if w != ii.PRIORITY_IGNORE))

print("\n" + "=" * 64)
print("  %d passed, %d failed" % (_passed, _failed))
for f in _FAILS:
    print("   x " + f)
print("=" * 64)
sys.exit(1 if _failed else 0)
