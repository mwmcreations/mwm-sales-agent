"""PATCH #138 — relationship.py, pure rules."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import relationship as r
PASS = FAIL = 0
def ok(c, label):
    global PASS, FAIL
    if c: PASS += 1; print("  ok   " + label)
    else: FAIL += 1; print("  FAIL " + label)

print("\n== classify")
ok(r.classify({}, client_hit=True)[0] == r.CLIENT, "a client lookup hit is a client")
ok(r.classify({"ig_we_follow": True}, client_hit=True)[0] == r.CLIENT, "client outranks follow")
ok(r.classify({"ig_we_follow": True})[0] == r.KNOWN, "someone we follow is a personal contact")
ok(r.classify({"ig_we_follow": True, "ad_referral": True})[0] == r.LEAD, "an ad click outranks a follow")
ok(r.classify({"ig_we_follow": True, "ad_id": "123"})[0] == r.LEAD, "ad_id alone also counts as an ad arrival")
ok(r.classify({"ig_we_follow": False})[0] == r.LEAD, "not followed -> lead")
ok(r.classify({"ig_we_follow": None})[0] == r.LEAD, "unknown follow -> lead (fail open)")
ok(r.classify({"ig_we_follow": "true"})[0] == r.LEAD, "a string is not a follow")
ok(r.classify(None)[0] == r.LEAD, "no record -> lead")

print("\n== follow flags")
ok(r.follow_flags({"is_business_follow_user": True, "is_user_follow_business": False}) == (True, False), "reads both flags")
ok(r.follow_flags({"name": "x"}) == (None, None), "missing -> unknown, not False")
ok(r.follow_flags({"is_business_follow_user": 1}) == (None, None), "1 is not true")
ok(r.follow_flags("nope") == (None, None), "non-dict -> unknown")
ok("is_business_follow_user" in r.PROFILE_FIELDS and r.BASIC_FIELDS == "name,username", "field lists")

print("\n== freshness")
ok(r.follow_check_due({}, 1000) is True, "never checked -> due")
ok(r.follow_check_due({"ig_follow_checked_ts": 1000}, 1000 + 3600) is False, "an hour old -> fresh")
ok(r.follow_check_due({"ig_follow_checked_ts": 0}, r.FOLLOW_TTL_S + 1) is True, "a week old -> due")
ok(r.follow_check_due({"ig_follow_checked_ts": "bad"}, 5) is True, "garbage ts -> due")

print("\n== quiet rules")
ok(r.should_stay_quiet(r.KNOWN, False) and r.should_stay_quiet(r.KNOWN, True), "personal contacts: always quiet")
ok(r.should_stay_quiet(r.CLIENT, True), "client share/reaction: quiet")
ok(not r.should_stay_quiet(r.CLIENT, False), "client question: Maya answers in client mode")
ok(not r.should_stay_quiet(r.LEAD, True) and not r.should_stay_quiet(r.LEAD, False), "leads: unchanged")

print("\n== text")
ok(r.attachment_text("ig_reel") == "[Shared a reel]", "reel label")
ok(r.attachment_text("story_mention") == "[Mentioned us in their story]", "story mention label")
ok(r.attachment_text("weird") == "[Sent an attachment]", "unknown type label")
n = r.quiet_note(r.KNOWN, "U01")
ok("<@U01>" in n and "did NOT reply" in n and "Reply in this thread" in n, "quiet note pings and instructs")
ok("<@" not in r.quiet_note(r.CLIENT, ""), "no ping id -> no broken mention")

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
