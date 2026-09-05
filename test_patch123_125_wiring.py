#!/usr/bin/env python3
"""
test_patch123_125_wiring.py — three silences, closed.

#123 · calendar_sync failed twice on 3 Sep with a Domain-Wide Delegation
       `unauthorized_client` error and then went quiet for 37 hours. Two
       causes: the DWD fallback was DEAD CODE (with_subject() and build()
       authenticate nothing, so the error surfaced far from the handler that
       was written to catch it), and nothing counted consecutive failures —
       loop() heartbeats BEFORE sync_once, so the watchdog stayed green while
       every tick achieved nothing.

#124 · `sms_consent_pull` could not be proven alive or dead from /health for
       six days. The poller heartbeats before the pull, a clean poll of zero
       rows prints nothing, and a missing WP_PORTAL_SECRET returns quietly
       behind an hourly rate limiter.

#125 · out-of-hours approvals lived ONLY in memory. Every deploy emptied the
       table: the request vanished, the nag thread had nothing to nag about,
       and neither Michael nor the lead was told. Found while shipping #119 —
       whose fix is worth nothing if the request it protects can evaporate.

Run: python3 test_patch123_125_wiring.py
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


APP = io.open("app.py", encoding="utf-8").read()
CS = io.open("calendar_sync.py", encoding="utf-8").read()


def fn(src, name, end="\ndef "):
    i = src.index("def %s(" % name)
    return src[i:src.index(end, i + len(name) + 5)]


# ── #123a · the DWD fallback can actually fire now ────────────────────────
svc = fn(APP, "_calsync_service")
ok("calendarList().list(maxResults=1)" in svc,
   "_calsync_service forces the token exchange inside the try — otherwise the "
   "unauthorized_client fallback below it is unreachable")
ok(svc.index("calendarList().list") < svc.index("except Exception as _cs_err"),
   "and the probe is INSIDE the try, not after it")
ok("unauthorized_client" in svc, "the fallback still only catches the two config errors")
ok(APP.count("calendarList().list(maxResults=1)") >= 3,
   "the booking form got the same probe — its fallback was dead for the same reason")


# ── #123b · a stuck sync is loud ──────────────────────────────────────────
ok("_CONSECUTIVE_FAILURES" in CS and "FAILURE_ALERT_AFTER" in CS,
   "consecutive failing ticks are counted")
ok("def _note_failure_streak(" in CS, "and there is one place that decides to speak")
ok("_note_failure_streak(summary)" in CS, "which sync_once actually calls")
streak = fn(CS, "_note_failure_streak")
ok("_FAILURE_ALERTED" in streak and "return" in streak,
   "the alarm fires ONCE, not every tick — an alert repeated is an alert ignored")
ok("working again" in streak, "and recovery is announced, so silence is never the all-clear")
ok("heartbeat is green" in streak,
   "the message names the actual trap: a live thread achieving nothing")
ok(CS.index("_CONSECUTIVE_FAILURES = 0") < CS.index("def _note_failure_streak"),
   "the counter is module-level state, not per-call")


# ── #124 · the consent bridge can be asked, not guessed ───────────────────
ok("_SMS_CONSENT_LAST" in APP and "def _sms_consent_note(" in APP,
   "the poll records its own outcome")
pull = fn(APP, "_sms_consent_pull")
ok("_sms_consent_note()" in pull, "a clean poll stamps success")
ok('_sms_consent_note("WP_PORTAL_SECRET not set")' in pull,
   "and the silent early return stamps the reason instead of vanishing")
poller = fn(APP, "_sms_consent_poller")
ok(poller.index("_sms_consent_pull()") < poller.index('_heartbeat("sms_consent_poller")',
                                                      poller.index("while True")),
   "inside the loop the heartbeat comes AFTER the pull — beating first is what "
   "kept the watchdog green for six days")
ok('"sms_consent": dict(_SMS_CONSENT_LAST)' in APP,
   "and /health carries it, which is the only place anyone was looking")


# ── #125 · a promise survives a deploy ────────────────────────────────────
ok("APPROVAL_STATE_KEY" in APP and "def _approvals_save(" in APP
   and "def _approvals_load(" in APP, "the approval table is persisted and rehydrated")
ok(APP.count("_approvals_save()") >= 4,
   "every mutation persists: create, approve, decline, expire")
save = fn(APP, "_approvals_save")
ok("_pgs.enabled()" in save, "it no-ops cleanly with no database rather than raising")
ok("_report_error(\"approvals_save\"" in save,
   "a failed write is reported — losing persistence must not be silent either")
ok("except Exception" in save,
   "but it never breaks a live approval, which is the more important promise")
load = fn(APP, "_approvals_load")
ok("APPROVAL_EXPIRED" in load,
   "anything that died while we were down is rehydrated as EXPIRED, not as live")
ok('req.get("token")' in load, "a row with no token is not an approval and is dropped")
ok(APP.index("_approvals_load()") < APP.index("threading.Thread(target=_approval_sweep"),
   "rehydration happens BEFORE the sweep starts, so it can nag about requests "
   "this process never saw created")
ok('"approvals": {' in APP and '"persisted": bool(_pgs.enabled())' in APP,
   "/health says whether approvals are actually durable this boot")


print("\n" + "=" * 60)
print("  PATCHES #123-#125 WIRING: %d passed, %d failed" % (PASS, FAIL))
print("=" * 60)
raise SystemExit(1 if FAIL else 0)
