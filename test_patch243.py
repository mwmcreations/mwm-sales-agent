"""PATCH #243 gate - Instagram connect (Business Login for Instagram).
Pure helpers in ig_connect + static wiring of the two routes in app.py.
Prints "N passed, M failed", then runs the #160 gate (which chains on)."""
import os
import re
import subprocess
import sys
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ig_connect as igc   # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


# scopes: the DM scope must never be dropped
check("scopes.messages_kept", "instagram_business_manage_messages" in igc.REQUIRED_SCOPES)
check("scopes.publish_insights", "instagram_business_content_publish" in igc.REQUIRED_SCOPES
      and "instagram_business_manage_insights" in igc.REQUIRED_SCOPES and "instagram_business_basic" in igc.REQUIRED_SCOPES)

# state
st = igc.new_state(now=1000)
check("state.ok", igc.state_ok(st, st["nonce"], now=1000 + 60))
check("state.wrong", not igc.state_ok(st, st["nonce"] + "x", now=1001))
check("state.expired", not igc.state_ok(st, st["nonce"], now=1000 + igc.STATE_TTL_S + 1))
check("state.future", not igc.state_ok(st, st["nonce"], now=999))
check("state.empty", not igc.state_ok({}, "a") and not igc.state_ok(None, "a") and not igc.state_ok(st, "") and not igc.state_ok(st, None))
check("state.unique", igc.new_state()["nonce"] != igc.new_state()["nonce"] and len(st["nonce"]) >= 24)

# authorize url
u = igc.authorize_url("123", "https://h.example/auth/instagram/callback", "NONCE")
q = parse_qs(urlparse(u).query)
check("url.host", u.startswith("https://www.instagram.com/oauth/authorize?"))
check("url.params", q["client_id"] == ["123"] and q["response_type"] == ["code"] and q["state"] == ["NONCE"]
      and q["redirect_uri"] == ["https://h.example/auth/instagram/callback"])
check("url.scopes", set(q["scope"][0].split(",")) == set(igc.REQUIRED_SCOPES))
check("url.no_secret", "secret" not in u.lower())

# code response parsing (both shapes)
t, uid, p = igc.parse_code_response({"data": [{"access_token": "T", "user_id": 42, "permissions": "a,b"}]})
check("parse.nested", t == "T" and uid == "42" and p == ["a", "b"])
t, uid, p = igc.parse_code_response({"access_token": "T2", "user_id": "7", "permissions": ["x", " y "]})
check("parse.flat", t == "T2" and uid == "7" and p == ["x", "y"])
check("parse.error", igc.parse_code_response({"error_type": "OAuthException"}) == (None, None, [])
      and igc.parse_code_response("nope") == (None, None, []) and igc.parse_code_response({"data": []}) == (None, None, []))

# missing scopes
check("missing.none", igc.missing_scopes(",".join(igc.REQUIRED_SCOPES) + ",instagram_business_manage_comments") == [])
check("missing.dm", igc.missing_scopes([s for s in igc.REQUIRED_SCOPES if s != "instagram_business_manage_messages"])
      == ["instagram_business_manage_messages"])
check("missing.empty", igc.missing_scopes(None) == list(igc.REQUIRED_SCOPES))

# account match
check("acct.same", igc.same_account({"user_id": "9"}, {"user_id": "9", "username": "x"})[0])
check("acct.diff", not igc.same_account({"user_id": "9"}, {"user_id": "10", "username": "mwm.creations"})[0])
check("acct.fallback_name", igc.same_account({}, {"user_id": "1", "username": "MWM.Creations"})[0])
check("acct.fallback_wrong", not igc.same_account({}, {"user_id": "1", "username": "someone"})[0])
check("acct.unreadable", not igc.same_account({"user_id": "9"}, {})[0])

# page escapes and never needs a token
pg = igc.result_page("<t>", ["a<b"])
check("page.escaped", "<t>" not in pg and "&lt;b" in pg)

# static wiring in app.py
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("wire.import", "import ig_connect as _igc" in SRC)
check("wire.routes", "@app.route('/admin/ig-connect', methods=['GET'])" in SRC and "@app.route(_igc.CALLBACK_PATH, methods=['GET'])" in SRC)
cb = SRC[SRC.index("def ig_connect_callback():"):SRC.index("# Run the exchange on module load (gunicorn worker boot)")]
# order: state -> single-use -> scopes -> long exchange -> account -> swap -> persist
i_state = cb.index("_igc.state_ok(")
i_clear = cb.index("_igc_save_state({})")
i_miss = cb.index("_igc.missing_scopes(perms)")
i_long = cb.index("_exchange_ig_short_token(short, INSTAGRAM_APP_SECRET)")
i_acct = cb.index("_igc.same_account(")
i_swap = cb.index("INSTAGRAM_ACCESS_TOKEN = new_token")
i_pers = cb.index("_persist_ig_token(new_token")
check("wire.order", i_state < i_clear < i_miss < i_long < i_acct < i_swap < i_pers)
check("wire.global", "global INSTAGRAM_ACCESS_TOKEN" in cb)
# the token never reaches a print, a Slack post or the page
for leak in ("print(", ):
    check("wire.no_print_in_callback", leak not in cb)
for name in ("new_token", "short", "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_APP_SECRET", "code"):
    for sink in ("_post_to_slack_async(", "_igc.result_page(", "_report_error("):
        for m in re.finditer(re.escape(sink), cb):
            seg = cb[m.start(): cb.find(")", m.start()) + 400]
            # crude: the call text up to its closing paren of the first line group
            call = cb[m.start(): m.start() + 600].split("\n    ")[0]
            bare = re.sub(r'"[^"\n]*"', '""', call.replace(sink, " "))   # ignore words inside string literals
            if re.search(r"[{(+,\s]" + re.escape(name) + r"[})\s,+]", bare):
                check(f"wire.no_leak.{name}.{sink}", False, call[:120])
check("wire.secret_not_in_url", "client_secret" not in SRC[SRC.index("def admin_ig_connect():"):SRC.index("def ig_connect_callback():")])
check("wire.post_body", "http_requests.post(_igc.CODE_EXCHANGE_URL, data={" in cb)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch160.py")], capture_output=True, text=True)
tail = (r_.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #160 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("chain: " + tail)
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
