#!/usr/bin/env python3
"""
test_patch113_wiring.py — PATCH #113, the wiring half.

sms_copy can be perfect and a client can still get nothing, or get two of the
same text, because the copy is only worth anything if the senders are wired
correctly. This reads app.py and proves five things:

  1. every sender goes through the shared guarded helper, not _send_sms;
  2. every sender declares itself TRANSACTIONAL;
  3. no sender can break the booking flow that called it;
  4. the reminder ladder still falls through to email when SMS is refused;
  5. the opt-in confirmation cannot fire twice, and cannot fire at all off a
     historical ledger row.

Run: python3 test_patch113_wiring.py
"""
import io

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


SRC = io.open("app.py", encoding="utf-8").read()

# ── §1 · ONE DOOR TO TWILIO, AND ONE DOOR TO THE COPY ──────────────────────
ok(SRC.count("Messages.json") == 1,
   "there is still exactly ONE place that posts to Twilio")
ok("import sms_copy as _sms_copy" in SRC, "the copy module is imported")
ok(SRC.count("_send_sms(") == 4,
   "_send_sms is called from exactly three places plus its definition "
   "(helper, re-engagement, opt-in) — a fourth caller means a sender "
   "skipped the guards")

helper = SRC.split("def _sms_transactional(")[1].split("\ndef ")[0]
ok("kind=SMS_KIND_TRANSACTIONAL" in helper,
   "the shared helper sends as TRANSACTIONAL — it is the booking senders' door")
ok("except Exception as _tx:" in helper,
   "the helper cannot raise: a booking must never fail because a text failed")
ok("_sc.to_e164(raw_phone)" in helper,
   "an undialable number is a named skip, not an exception")
ok("body = body_fn()" in helper,
   "copy is built INSIDE the try, so a refusing copy function cannot take "
   "down the caller")

# ── §2 · IDEMPOTENCY IS CLAIMED, THEN RELEASED IF NOTHING WENT OUT ─────────
ok("_pg.save_state(idem_key, True)" in helper, "the key is claimed before the send")
ok(helper.index("_pg.save_state(idem_key, True)") < helper.index("body = body_fn()"),
   "...before, not after — a retry arriving mid-flight must find it taken")
ok("_sms_idem_release(idem_key)" in helper, "and released when nothing was sent")
ok(helper.count("_sms_idem_release(idem_key)") >= 2,
   "released on BOTH the refusal path and the exception path — a quiet-hours "
   "refusal must not cancel the message forever")
ok('return False, "idem_unreadable"' in helper,
   "an unreadable marker fails CLOSED rather than risking a double send")
rel = SRC.split("def _sms_idem_release(")[1].split("\ndef ")[0]
ok("_pg.save_state(idem_key, False)" in rel, "release clears the claim")
ok("except Exception as _rx" in rel,
   "a failed release is survivable — one message unsent beats a loop")

# ── §3 · THE OPT-IN CONFIRMATION HAS ALL THREE GUARDS ──────────────────────
oc = SRC.split("def _sms_optin_confirm(")[1].split("\ndef ")[0]
ok('return False, "already_yes"' in oc,
   "guard 1: a poller re-reading the same row is not a new opt-in")
ok('return False, "consent_too_old"' in oc,
   "guard 2: a backfill of historical rows cannot text everyone")
ok("SMS_OPTIN_CONFIRM_MAX_AGE_S" in oc, "...using an explicit freshness window")
ok('return False, "already_confirmed"' in oc, "guard 3: a permanent marker")
ok(oc.index("_pg.save_state(_key, True)") < oc.index("_send_sms("),
   "the marker is written BEFORE the send — one duplicate is a complaint, "
   "a loop is a suspension")
ok('return False, "marker_unreadable"' in oc and 'return False, "marker_unwritable"' in oc,
   "an unusable marker fails closed both ways")
ok('return False, "unreadable_ts"' in oc, "an unreadable timestamp fails closed")
ok("kind=SMS_KIND_TRANSACTIONAL" in oc,
   "the confirmation is transactional — it is a receipt, not a promotion")
ok("marketing=bool(rec.get(\"marketing\"))" in oc,
   "and its WORDING reflects which boxes were actually ticked")
cs = SRC.split("def _sms_consent_set(")[1].split("\ndef ")[0]
ok("_sms_optin_confirm(lead_phone, rec, _prev)" in cs,
   "it fires from _sms_consent_set, so form / Maya / in-person all behave alike")
ok("_prev = _sms_consent_get(lead_phone)" in cs
   and cs.index("_prev = _sms_consent_get") < cs.index('_pg.save_state(f"sms_consent:'),
   "the previous record is read BEFORE the overwrite, or every write would "
   "look like a transition")
ok("except Exception as _ox" in cs,
   "a failed confirmation never loses the consent it was confirming")

# ── §4 · THE STUDIO BOOKING SENDER ─────────────────────────────────────────
sb = SRC.split("def _sb_process(evt):")[1].split("\n    threading.Thread")[0]
ok('_sms_copy.studio_booking_confirmed(' in sb, "a portal booking texts the client")
ok('idem_key=f"sms_booking_confirmed:{bid}"' in sb,
   "keyed on the booking id, so a WordPress retry cannot double-text")
ok('if _sb_state in ("ok", "degraded"):' in sb.split("_sms_transactional(")[0][-200:],
   "it only fires when the slot is genuinely held — confirming a booking that "
   "is not on the calendar would be a lie the client acts on")
ok("_sms_copy.pretty_date(date)" in sb and "_sms_copy.pretty_time(start)" in sb,
   "the portal's raw '2026-09-04' and '10:00' are never shown to a client")
ok("STUDIO_ADDRESS" in sb.split("studio_booking_confirmed(")[1][:200],
   "the address is carried, matching the registered sample")

# ── §5 · THE FILM SHOOT SENDER ─────────────────────────────────────────────
rs = SRC.split("def roadmap_shoot_webhook(")[1].split("\n@app.route")[0]
ok("_sms_copy.film_shoot_confirmed(" in rs, "a confirmed filming day texts the client")
ok("_CLIENT_ROSTER.find({\"email\": email})" in rs,
   "the phone is resolved from the roster BY EMAIL ONLY — a business-name "
   "match could text the wrong client about the wrong shoot")
ok('"name": name' not in rs.split("_CLIENT_ROSTER.find(")[1][:120],
   "...with no fuzzy name or business signal in the lookup")
ok('_rs_why = "no_email_on_payload"' in rs,
   "a payload with no email is a named skip")
ok('_TALLY.bump("sms.shoot_confirmed", "no_roster_phone")' in rs,
   "no roster match is a NAMED skip: we do not guess a number to text")
ok('idem_key="sms_shoot_confirmed:%s:%s:%s" % (cid, date, start)' in rs,
   "keyed on campaign AND slot, so a re-confirmed day at a NEW time still texts")
ok("except Exception as _rs_sms" in rs,
   "and the filming day is never lost because a text failed")

# ── §6 · THE LADDER RUNG IS A RUNG, NOT A BRANCH ───────────────────────────
lad = SRC.split("PATCH #113 · the SMS rung")[1].split("if _sent_via:")[0]
ok("_sms_copy.session_reminder(" in lad, "the ladder can send an SMS reminder")
ok('if not _sent_via and _lp and is_dialable("+" + _lp):' in lad,
   "it only runs when WhatsApp did NOT already deliver")
ok(lad.index("_sms_transactional(") < lad.index("S-6 email fallback"),
   "SMS sits between WhatsApp and email")
ok("if _sms_ok:" in lad and '_sent_via = "SMS"' in lad,
   "a successful SMS marks the touch as sent")
ok("if not _sent_via and _email" in lad,
   "and a REFUSED SMS falls through to email exactly as before — nothing a "
   "client gets today is taken away")
ok('idem_key=f"sms_reminder:{event_id}:{stage_h}"' in lad,
   "keyed on event AND tier, so each rung sends at most once")
ok("stage_h, _fn, _when_long, _time_str" in lad,
   "the reminder carries the real date and time, not a horizon phrase")

# ── §7 · AN INBOUND REPLY REACHES A HUMAN ──────────────────────────────────
# Our own reminder copy invites a reply. That promise has to be honoured.
inb = SRC.split("def sms_inbound_webhook(")[1].split("\n@app.route")[0]
ok("_post_assignment(" in inb,
   "an inbound text raises an ASSIGNMENT, not a passive channel message")
ok('owner="MICHAEL"' in inb, "with a named owner")
ok("deadline=" in inb, "and a deadline")
ok("exact_text=body[:400]" in inb, "quoting the client verbatim")
ok("_CLIENT_ROSTER.find(" in inb,
   "and naming the client where the roster knows the number")
ok('_pg.save_state(f"do_not_sms:{frm}", True)' in inb,
   "STOP still writes do_not_sms — the opt-out path is untouched")
ok(inb.index("STOPALL") < inb.index("_post_assignment("),
   "and STOP is handled BEFORE the assignment, so an opt-out never becomes a "
   "task for Michael to reply to")

# ── §8 · /health INVENTORIES THE SENDERS ───────────────────────────────────
rd = SRC.split("def _sms_readiness(")[1].split("\ndef ")[0]
for s in ("optin_confirmation", "studio_booking_confirmed", "film_shoot_confirmed",
          "session_reminder", "reengagement"):
    ok('"%s"' % s in rd, "/health lists the %s sender" % s)
ok('"reengagement": "marketing' in rd,
   "and marks the only marketing sender as marketing")
ok(rd.count("transactional —") == 4, "the other four are marked transactional")

print("\n%d passed, %d failed" % (PASS, FAIL))
raise SystemExit(1 if FAIL else 0)
