#!/usr/bin/env python3
"""
test_known_client.py — PATCH #110.

Jaysee Soto paid $1,200 on 26 Aug. On 29 Aug the machine announced him as a
NEW LEAD because he happened to message from Instagram instead of WhatsApp.

The fix must be strict in one specific direction. Announcing a client as a
lead is embarrassing and costs a few automated messages. Deciding a REAL new
lead is an existing client would delete a prospect from the pipeline with no
error and no card — nobody would ever find it. So every ambiguous case below
must resolve to "not a client".

Run: python3 test_known_client.py
"""
import sys

import known_client as K

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


CLIENTS = [
    {"name": "Jaysee Soto", "business": "Altamonte Family Hearing",
     "email": "jsoto@altamontefamilyhearing.com", "phone": "whatsapp:+14075552194",
     "outcome": "Won", "product": "Studio Package"},
    {"name": "Marcia Cardim", "business": "Projeto de Vida",
     "email": "ediasm@icloud.com", "phone": "+13215551000", "product": "Studio 4hr/month"},
    {"name": "Just A Lead", "business": "Some Other Company",
     "email": "lead@example.com", "phone": "+14075559999", "outcome": ""},
]
IDX = K.build_client_index(CLIENTS)


# ── §1 · WHO COUNTS AS A CLIENT ────────────────────────────────────────────
ok(K.is_client_record({"outcome": "Won"}), "outcome Won is a client")
ok(K.is_client_record({"outcome": "won"}), "case does not matter")
ok(K.is_client_record({"product": "Studio Package"}), "a product on the record is a client")
ok(K.is_client_record({"status": "Client — Studio Package"}), "a client status is a client")
ok(not K.is_client_record({"outcome": "Lost"}), "Lost is not a client")
ok(not K.is_client_record({"status": "New Lead"}), "a new lead is not a client")
ok(not K.is_client_record({}), "an empty record is not a client")
ok(not K.is_client_record(None) and not K.is_client_record("nope"),
   "non-dict input is refused, not crashed on")
ok(not K.is_client_record({"product": "   "}), "whitespace is not a product")

ok(len(IDX["businesses"]) == 2, "only the two paying clients are indexed")
ok("some other company" not in IDX["businesses"],
   "the non-client is NOT in the index — this is the whole safety property")


# ── §2 · THE ACTUAL REGRESSION ─────────────────────────────────────────────
# The Instagram card carried the business from his profile and nothing else.
hit, why = K.match_known_client({"business": "Altamonte Family Hearing"}, IDX)
ok(hit and why.startswith("business:"),
   "the 29 Aug Instagram lead is recognised as an existing client (%s)" % why)

ok(K.match_known_client({"business": "altamonte family hearing"}, IDX)[0],
   "case-insensitive")
ok(K.match_known_client({"business": "Altamonte Family Hearing, LLC"}, IDX)[0],
   "a legal suffix does not defeat the match")
ok(K.match_known_client({"business": "The Altamonte Family Hearing"}, IDX)[0],
   "a leading article does not defeat the match")
ok(K.match_known_client({"email": "JSoto@AltamonteFamilyHearing.com"}, IDX)
   == (True, "email"), "email matches regardless of case")
ok(K.match_known_client({"phone": "instagram:1234567890123"}, IDX)[0] is False,
   "an Instagram id is never read as a phone number")
ok(K.match_known_client({"phone": "4075552194"}, IDX) == (True, "phone"),
   "the same number without a country code still matches")
ok(K.match_known_client({"phone": "whatsapp:+1 (407) 555-2194"}, IDX)[0],
   "formatting does not defeat the phone match")


# ── §3 · THE DIRECTION THAT MUST NEVER GO WRONG ────────────────────────────
ok(K.match_known_client({"business": "Hearing"}, IDX)[0] is False,
   "one generic word never identifies a client")
ok(K.match_known_client({"business": "Studio"}, IDX)[0] is False,
   "nor does 'Studio'")
ok(K.normalize_business("Hearing") == "",
   "a single-token business normalises to empty, not to itself")
ok(K.match_known_client({"business": "Altamonte Family Hearing Center"}, IDX)[0] is False,
   "a LONGER name is a different business — no substring matching")
ok(K.match_known_client({"business": "Family Hearing"}, IDX)[0] is False,
   "a shorter fragment is not the same business either")
ok(K.match_known_client({"name": "Jaysee Soto"}, IDX)[0] is False,
   "a person's NAME alone never matches — there is more than one Jaysee")
ok(K.match_known_client({"business": "Some Other Company"}, IDX)[0] is False,
   "a business that is only a lead is not treated as a client")
ok(K.match_known_client({"business": "", "email": "", "phone": ""}, IDX)
   == (False, "no_match"), "empty fields never match empty index entries")
ok(K.match_known_client({}, IDX) == (False, "no_match"), "an empty candidate matches nothing")
ok(K.match_known_client({"business": "Altamonte Family Hearing"}, {})
   == (False, "no_match"), "an empty index matches nothing")
ok(K.match_known_client(None, IDX) == (False, "no_match"), "None is refused")
ok(K.match_known_client({"email": "not-an-email"}, IDX)[0] is False,
   "a malformed email is discarded, not matched")
ok(K.match_known_client({"phone": "12345"}, IDX)[0] is False,
   "too few digits never matches")

# An index built from records with blank fields must not create a "" bucket
# that everything then matches against.
blank_idx = K.build_client_index([{"outcome": "Won", "business": "", "email": "", "phone": ""}])
ok(blank_idx == {"businesses": set(), "emails": set(), "phones": set()},
   "blank client fields add nothing to the index")
ok(K.match_known_client({"business": "Anything At All"}, blank_idx)[0] is False,
   "and so nothing matches against them")

# ── §4 · ORDER OF EVIDENCE ─────────────────────────────────────────────────
both = {"email": "jsoto@altamontefamilyhearing.com", "business": "Altamonte Family Hearing"}
ok(K.match_known_client(both, IDX) == (True, "email"),
   "email is reported ahead of business — the stronger signal names itself")

print("\nPATCH110_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  KNOWN CLIENT (Patch #110): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
