"""PATCH #137 wiring — client review pages in app.py + the Valente review on disk."""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import client_review as cr

PASS = FAIL = 0


def ok(c, label):
    global PASS, FAIL
    if c:
        PASS += 1; print("  ok   " + label)
    else:
        FAIL += 1; print("  FAIL " + label)


SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
print("\n== app.py")
i = SRC.index("import client_review as _cr")
ok(SRC.index("_vi_routes.register(") < i < SRC.index('if __name__ == "__main__":'), "registered after VI, before __main__")
blk = SRC[SRC.rindex("try:", 0, i):SRC.index("wiring skipped", i)]
ok("except Exception as _crx" in SRC[i:i + 800], "a review-page failure cannot stop the boot")
ok("_admin_secret_ok" in SRC[i:i + 400] and "session_ok=_cr_session_ok" in SRC[i:i + 400], "admin = ?secret= or an MWM sign-in")
ok('s.get("role") == _va.ROLE_MWM' in SRC or '_s.get("role") == _va.ROLE_MWM' in SRC, "only the MWM role, not school sign-ins")

print("\n== the Valente review on disk")
R = cr.load_reviews(os.path.join(HERE, "reviews"))
rv = R.get("valente-2026-09-18")
ok(rv is not None, "review loads")
ok(len(rv.order) == 86 and len(set(rv.order)) == 86, "86 unique segments")
ok(all(re.match(r"^C\d{4}_\d{2}$", k) for k in rv.order), "keys look like C0022_01")
ok(len(rv.reviewers) == 2 and all(re.match(r"^[0-9a-f]{64}$", h) for h in rv.reviewers), "two reviewers, stored as sha256 only")
ok(rv.slack_channel == "C0BM0EETDLL", "pings go to #eddie")
cfg = open(os.path.join(HERE, "reviews", "valente-2026-09-18", "review.json")).read()
ok(not re.search(r'"token"\s*:', cfg), "no raw token in the repo")
page = open(rv.page_path, encoding="utf-8").read()
for must, label in (('name="referrer" content="no-referrer"', "no-referrer"), ('name="robots"', "noindex meta"),
                    ("[hidden]{display:none!important}", "sheets hide on our hosting"),
                    ("API+'/answer'", "posts each change"), ("QKEY", "offline queue"),
                    ('name="viewport"', "phone viewport")):
    ok(must in page, "page: " + label)
for bad in ("Send results", "clipboard", "sendb"):
    ok(bad not in page, "page: no '%s'" % bad)
_dec = json.JSONDecoder()
data = _dec.raw_decode(page[page.index("const DATA=") + len("const DATA="):])[0]
ok([d["k"] for d in data] == rv.order, "page's cards == server's segments, same order")
groups = _dec.raw_decode(page[page.index("GROUPS=") + len("GROUPS="):])[0]
names = [o for g in groups for o in g[1]]
ok(len(names) == 79 and sum(1 for n in names if n.startswith("95 ")) == 2, "79 picker names, both 95s present verbatim")

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
