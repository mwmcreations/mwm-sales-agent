#!/usr/bin/env python3
"""
test_client_roster.py — PATCH #111.

Michael, 29 Aug: "sometimes on other clients, they mark us on Instagram, and
because of the bot, it always kinda try to schedule a studio visit even though
they are already clients. It's kinda awkward."

Patch #110 only knew the clients this machine watched convert. This holds the
portal's own client table, which is the actual answer to "who pays us".

The two behaviours most worth defending are both about NOT losing the roster:
a failed refresh must keep the old one, and a suspiciously empty result must be
refused. Fourteen clients do not resign at once, but WordPress does time out.

Run: python3 test_client_roster.py
"""
import sys

import client_roster as R

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


# Shaped exactly like the portal's mwm_studio_list_clients response.
PORTAL = [
    {"id": 18, "name": "JAYSEE SOTO", "email": "jsoto@altamontefamilyhearing.com",
     "package_name": "Studio Package", "contract_hours": "12.00",
     "hours_used": "0.00", "contract_start_date": "2026-08-26",
     "contract_end_date": "2026-11-24", "active": "1"},
    {"id": 5, "name": "Iris Rodriguez Delgado", "email": "iris@elevalomedia.com",
     "package_name": "4-Hour Studio Package", "contract_hours": "12.00",
     "hours_used": "7.00", "contract_end_date": "2026-11-01", "active": "1"},
    {"id": 8, "name": "Camila silveira", "email": "camilasalesnj@gmail.com",
     "package_name": "Studio Package", "contract_hours": "4.00",
     "hours_used": "4.00", "contract_end_date": "2026-08-04", "active": "1"},
]


# ── §1 · NORMALISATION ─────────────────────────────────────────────────────
row = R.normalize_row(PORTAL[1])
ok(row["email"] == "iris@elevalomedia.com", "email is normalised")
ok(row["hours_left"] == 5.0, "hours_left is derived: 12 - 7 = %s" % row["hours_left"])
ok(row["outcome"] == "Won",
   "every roster row is marked a client — it IS the paying-clients table")
ok(row["active"] is True, "active '1' reads as True")
ok(R.normalize_row({"active": "0", "name": "X"})["active"] is False, "'0' reads as False")
ok(R.normalize_row({"name": "No Email"}) is not None, "a name alone is still a row")
ok(R.normalize_row({}) is None, "an empty row is dropped")
ok(R.normalize_row("nope") is None, "a non-dict is dropped, not crashed on")
ok(R.normalize_row({"name": "X", "contract_hours": "bad"})["contract_hours"] == 0.0,
   "an unparseable number degrades to 0 rather than raising")
ok(R.normalize_row({"name": "X", "contract_hours": 4, "hours_used": 9})["hours_left"] == 0.0,
   "hours_left never goes negative")


# ── §2 · REFRESH, AND THE TWO WAYS IT MUST REFUSE ──────────────────────────
r = R.Roster()
ok(r.summary()["clients"] == 0, "starts empty")
ok(r.is_stale() is True, "and starts stale, so nothing trusts it yet")

ok(r.refresh(lambda: PORTAL) == (True, 3, "ok"), "a good fetch loads three clients")
ok(r.summary()["clients"] == 3 and r.summary()["stale"] is False, "and is no longer stale")

ok(r.refresh(lambda: None) == (False, 3, "unreachable"),
   "an unreachable portal does NOT empty the roster")
ok(r.summary()["clients"] == 3, "the three clients are still held")

ok(r.refresh(lambda: [])[2] == "empty_refused",
   "a suspiciously empty result is refused over a roster we already hold")
ok(r.summary()["clients"] == 3, "and again the roster survives")


def _boom():
    raise RuntimeError("WP timed out")


ok(r.refresh(_boom) == (False, 3, "exception"), "a raising fetch is caught")
ok(r.summary()["clients"] == 3, "and still does not lose the roster")
ok(r.refresh(lambda: "not a list")[2] == "bad_payload", "a wrong payload type is refused")
ok(r.summary()["last_error"] != "", "and the reason is recorded for /health")

empty = R.Roster()
ok(empty.refresh(lambda: [])[0] is True,
   "an empty result IS accepted when we hold nothing — a real empty portal")


# ── §3 · FINDING A CLIENT WITH ONLY NAME AND EMAIL ─────────────────────────
# The portal roster carries no company and no phone. This is the case that
# decides whether the whole patch is useful.
hit, why, rec = r.find({"name": "Bald Hearing Guy \U0001f4cdAltamonte Family Hearing"})
ok(hit, "the Instagram display name matches a roster client")
ok(rec and rec["id"] == 18, "and resolves to the right person (%s)" % (rec or {}).get("name"))
ok("domain" in why, "matched via the email domain, since the roster has no company (%s)" % why)

hit2, _, rec2 = r.find({"email": "IRIS@elevalomedia.com"})
ok(hit2 and rec2["id"] == 5, "an email matches regardless of case")

ok(r.find({"name": "Someone New"})[0] is False, "a stranger does not match")
ok(r.find({"business": "Orlando Dental Group"})[0] is False, "nor an unrelated business")
ok(r.find({"email": "someone@gmail.com"})[0] is False,
   "a consumer mail domain never matches — camilasalesnj@gmail.com is on the "
   "roster and must not make every gmail user a client")
ok(R.Roster().find({"email": "jsoto@altamontefamilyhearing.com"})
   == (False, "roster_empty", None),
   "an unloaded roster matches nobody and says why")


# ── §4 · WHAT /health WILL SHOW ────────────────────────────────────────────
sm = r.summary()
for k in ("clients", "active", "expired", "age_s", "stale", "last_error"):
    ok(k in sm, "summary reports %s" % k)
ok(sm["active"] + sm["expired"] == sm["clients"], "active and expired account for all of them")

print("\nPATCH111_GATE_RESULT: " + ("PASS" if FAIL == 0 else "FAIL"))
print("\n" + "=" * 62)
print("  CLIENT ROSTER (Patch #111): {} passed, {} failed".format(PASS, FAIL))
print("=" * 62)
sys.exit(1 if FAIL else 0)
