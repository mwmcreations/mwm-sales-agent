"""PATCH #142 — Valente review v2 (the cut, 64 clips): timing flags stored beside
technique and note; a review without the best-take star; the hosted page."""
import json, os, sys, types
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import client_review as cr
PASS = FAIL = 0
def ok(c, label):
    global PASS, FAIL
    if c: PASS += 1; print("  ok   " + label)
    else: FAIL += 1; print("  FAIL " + label)

print("\n== flags: validation")
k, f = cr.clean_fields({"segment_key": "T01", "flags": ["late", "ok", "late"]})
ok(f == {"flags": ["ok", "late"]}, "deduped, canonical order")
ok(cr.clean_fields({"segment_key": "T01", "flags": []})[1] == {"flags": []}, "empty list clears")
ok(cr.clean_fields({"segment_key": "T01", "flags": None})[1] == {"flags": []}, "null clears")
for bad in (["late", "bogus"], "late", [1], {"a": 1}):
    try:
        cr.clean_fields({"segment_key": "T01", "flags": bad}); ok(False, "rejects %r" % (bad,))
    except ValueError:
        ok(True, "rejects %r" % (bad,))
k, f = cr.clean_fields({"segment_key": "T05", "technique": "95 Rear naked choke defense", "note": "x", "flags": ["notech"]})
ok(set(f) == {"technique", "note", "flags"}, "the v2 body {segment_key, technique?, note?, flags?}")
ok(set(cr.FLAGS) == {"ok", "early", "late", "short", "long", "wrong", "notech"}, "the seven flags EDDIE listed")

print("\n== flags: rows, storage helpers, csv")
rows = {}
ch = cr.apply_answer(rows, {}, "T01", {"flags": ["early"]})
ok(rows["T01"]["flags"] == ["early"] and ch["T01"]["flags"] == ["early"], "stored and echoed back")
cr.apply_answer(rows, {}, "T01", {"technique": "12 Jab"})
ok(rows["T01"]["flags"] == ["early"] and rows["T01"]["technique"] == "12 Jab", "naming keeps the flags")
cr.apply_answer(rows, {}, "T01", {"flags": []})
ok(rows["T01"]["flags"] == [], "flags can be cleared")
ok(cr.flags_db(["late", "ok"]) == "ok,late" and cr.flags_from_db("ok,late,junk") == ["ok", "late"], "db text round trip, junk dropped")
ok(cr.flags_from_db("") == [] and cr.flags_from_db(None) == [], "empty db value = no flags")
old = cr.apply_answer({}, {}, "A1", {"note": "good"})
ok(old == {"A1": {"technique": None, "is_best": False, "note": "good"}}, "v1 rows unchanged (no flags key unless set)")

print("\n== the new review on disk")
R = cr.load_reviews(os.path.join(HERE, "reviews"))
ok("valente-2026-09-18" in R, "the old review is still there, untouched")
rv = R.get("valente-2026-09-18-cut")
ok(rv is not None, "new review_id valente-2026-09-18-cut loads")
ok(rv and len(rv.order) == 64 and rv.order[0] == "T01" and rv.order[-1] == "T64", "64 segments T01 … T64")
ok(rv and rv.best_take is False and R["valente-2026-09-18"].best_take is True, "cut review has no star; old one keeps it")
ok(rv and rv.slack_channel == "C0BM0EETDLL", "pings go to #eddie")
ok(rv and len(rv.reviewers) == 2 and not (set(rv.reviewers) & set(R["valente-2026-09-18"].reviewers)), "new tokens (2), none reused")
ok(not os.path.exists(os.path.join(HERE, "reviews", "valente-2026-09-18-cut", "TOKENS_DO_NOT_COMMIT.json")), "no raw token in the repo")
csvt = cr.to_csv(rv, [{"label": "G", "segment_key": "T01", "technique": "12 Jab", "is_best": False,
                       "note": "n", "updated_at": "t", "flags": ["early", "short"]}])
ok("flags,flags_text" in csvt.splitlines()[0] and "early short" in csvt and "starts too early; ends too soon" in csvt, "csv has flags + readable text")
prog = cr.progress(rv, {"h": {"T01": {"technique": "12 Jab", "flags": ["late"]}, "T02": {"flags": ["ok"]}}})
ok(prog[0]["flagged"] == 1 and prog[0]["flag_ok"] == 1 and prog[0]["named"] == 1 and prog[0]["of"] == 64, "admin counts: flagged / marked right / named")
ok("flags" in cr._ADMIN_PAGE and "Flagged clips" in cr._ADMIN_PAGE and "best_take" in cr._ADMIN_PAGE, "admin table shows flags")
ok(any("ADD COLUMN IF NOT EXISTS flags" in d for d in cr.DDL), "schema migration adds the flags column")

print("\n== the hosted page")
P = open(os.path.join(HERE, "reviews", "valente-2026-09-18-cut", "page.html"), encoding="utf-8").read()
ok('name="referrer" content="no-referrer"' in P and "noindex" in P, "no-referrer + noindex")
ok("[hidden]{display:none!important}" in P, "[hidden] rule kept")
ok('src="p/${esc(d.k)}.jpg"' in P and 'v.src="c/"+k+".mp4"' in P and "posters/" not in P and "clips/" not in P, "media under <token>/p and <token>/c")
ok("enqueue(k,'flags',r.flags.slice())" in P and "enqueue(k,'technique',val||null)" in P
   and "enqueue(k,'technique',pt)" in P and P.count("enqueue(k,'note',nt.value)") == 2, "every change posts its field")
ok("enqueue(k,'is_best'" not in P, "is_best is never sent")
ok("img.replaceWith(v)" in P, "tap still replaces only the thumbnail")
ok('data-f="nobest"' not in P, "the dead 'No best take' filter is gone")
ok("render(); syncUI(); pull();" in P and "API+'/answers'" in P and "API+'/answer'" in P, "boots from the server, queue-and-retry")
ok('"k":"T64"' in P and P.count('"k":"T') == 64, "64 segments inlined")

print("\n== routes (fake storage)")
try:
    from flask import Flask
except ImportError:
    Flask = None
    print("  (flask missing here: route checks run in the cloud e2e)")
if Flask:
    DB, KV, PINGS = {}, {}, []
    sys.modules["pg_store"] = types.SimpleNamespace(load_state=lambda k, d=None: KV.get(k, d),
                                                    save_state=lambda k, v: KV.__setitem__(k, v), enabled=lambda: True)
    cr.db_answer = lambda review, h, key, fields, ts=None, ua="": cr.apply_answer(DB.setdefault((review.review_id, h), {}), review.clip_of, key, fields)
    cr.db_answers_for = lambda rid, h: {k: dict(v) for k, v in DB.get((rid, h), {}).items()}
    app = Flask(__name__)
    cr.register(app, admin_ok=lambda s: s == "adm", notify=lambda ch, t: PINGS.append((ch, t)), reviews=R)
    c = app.test_client()
    TOK = "Zz_" + "q" * 30
    rv.reviewers[cr.sha(TOK)] = "Test"
    r = c.post("/api/%s/answer" % TOK, json={"segment_key": "T07", "flags": ["long", "late"]})
    ok(r.status_code == 200 and r.get_json()["changed"]["T07"]["flags"] == ["late", "long"], "POST flags -> 200, canonical echo")
    r = c.post("/api/%s/answer" % TOK, json={"segment_key": "T07", "flags": ["nope"]})
    ok(r.status_code == 400, "bad flag -> 400")
    r = c.post("/api/%s/answer" % TOK, json={"segment_key": "C0022_01", "note": "x"})
    ok(r.status_code == 400, "old-style key refused on the new review")
    g = c.get("/api/%s/answers" % TOK).get_json()
    ok(g["ok"] and g["review_id"] == "valente-2026-09-18-cut" and g["answers"]["T07"]["flags"] == ["late", "long"], "GET answers restores flags")
    pg = c.get("/r/%s/" % TOK)
    ok(pg.status_code == 200 and b"Technique review" in pg.data and pg.headers.get("Referrer-Policy") == "no-referrer", "page served, no-referrer")
    import time; time.sleep(0.3)
    ok(any("first answer" in t and "valente-2026-09-18-cut" in t for _, t in PINGS), "first-answer ping names the new review_id")

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
