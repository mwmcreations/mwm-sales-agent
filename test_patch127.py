#!/usr/bin/env python3
"""
test_patch127.py — the endpoint that could delete any lead, from anywhere.

WHAT IT WAS
───────────
    @app.route('/webhook-test', methods=['POST'])      # no auth of any kind
    test_sender = data.get("sender", "smoke_test_000") # caller's choice
    ...
    lead_data.pop(test_sender, None)                   # hard delete

`LeadStore.pop` records the key in leads_db._deleted, and flush() turns that
into a real DELETE against the leads table within FLUSH_INTERVAL (15 seconds).
So one unauthenticated POST naming a real lead wrote a fake message into that
person's conversation history and then erased them from memory AND from
Postgres — permanently, silently, with no alert and no audit line.

Verified from the open internet on 5 Sep 2026:
    GET /webhook-test        -> 405   (route exists, wrong method)
    GET /admin/approvals     -> 401   (what a guarded route looks like)
    GET /definitely-not-here -> 404   (what an absent route looks like)
Nothing was guarding it.

This is the ONLY code path in the repository that deletes a lead — every
other `pop`/`del` against lead_data does not exist. It is therefore the only
candidate mechanism for the eight booked records that vanished at ~03:20 ET
on 1 September with no purge and no migration run.

Run: python3 test_patch127.py
"""
import io
import re

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL: %s" % label)


APP = io.open("app.py", encoding="utf-8").read()
i = APP.index("def webhook_smoke_test(")
FN = APP[i:APP.index("\n@app.route", i)]


# ── 1 · lock one: it is no longer anonymous ───────────────────────────────
ok("_admin_secret_ok(" in FN, "the smoke test now requires the admin secret")
ok('"unauthorized"' in FN and "401" in FN, "and refuses with 401 rather than running")
ok(FN.index("_admin_secret_ok") < FN.index("test_sender ="),
   "the check runs BEFORE the sender is read — no work happens for a stranger")


# ── 2 · lock two: even WITH the secret it cannot name a real person ───────
ok('startswith("smoke_test_")' in FN,
   "the sender is pinned to a synthetic namespace")
ok(FN.index('startswith("smoke_test_")') < FN.index("_handle_incoming("),
   "and pinned before the handler runs, not after")
ok("400" in FN, "a real-looking sender is refused, not silently rewritten")
ok("deletes the lead it creates" in FN,
   "the refusal explains itself to whoever reads the response")


# ── 3 · lock three: it cannot delete what it did not create ───────────────
ok("_preexisting" in FN, "the endpoint records whether the key already existed")
ok(FN.index("_preexisting =") < FN.index("_handle_incoming("),
   "checked before the handler could create it")
ok("if not _preexisting:" in FN,
   "and the cleanup is conditional — an existing record is never popped")
_cleanup = FN[FN.index("Clean up test data"):]
ok("lead_data.pop(test_sender, None)" in _cleanup,
   "the cleanup still happens for genuinely synthetic keys")
ok(_cleanup.index("if not _preexisting:") < _cleanup.index("lead_data.pop"),
   "the guard sits above the pop, not beside it")


# ── 4 · the standing fact this patch rests on ─────────────────────────────
# If a second deletion path ever appears, this test should fail and somebody
# should have to think about it again.
# Count CODE only. This check failed on its first run because PATCH #127's own
# comment quotes `lead_data.pop(test_sender)` — the second time in two days a
# test of mine read prose and believed it. Strip comment lines first.
_code = "\n".join(l for l in APP.split("\n") if not l.lstrip().startswith("#"))
_pops = re.findall(r"lead_data\.(?:pop|clear)\(|del lead_data\[", _code)
ok(len(_pops) == 1,
   "there is still exactly ONE place in app.py that removes a lead — found %d"
   % len(_pops))


# ── 5 · the neighbours are, and stay, guarded ─────────────────────────────
for name in ("submit_post_visit_templates", "update_whatsapp_profile_photo",
             "admin_ig_token_exchange", "admin_ig_disable_auto_replies"):
    j = APP.index("def %s(" % name)
    body = APP[j:j + 4000]
    ok(bool(re.search(r"BRIEFING_TOKEN|_admin_secret_ok", body)),
       "/admin route %s is still authenticated" % name)


print("\n" + "=" * 60)
print("  PATCH #127: %d passed, %d failed" % (PASS, FAIL))
print("=" * 60)
raise SystemExit(1 if FAIL else 0)
