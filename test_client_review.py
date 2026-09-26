"""PATCH #137 — client review pages (Valente Brothers first)."""
import hashlib, json, os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import client_review as cr

PASS = FAIL = 0


def ok(c, label):
    global PASS, FAIL
    if c:
        PASS += 1; print("  ok   " + label)
    else:
        FAIL += 1; print("  FAIL " + label)


CLIP = {"A1": "C1", "A2": "C1", "A3": "C1", "B1": "C2", "B2": "C2"}
T52 = "52 Headlock defense (attacker upright)"
T95a = "95 Rear choke defense"
T95b = "95 Rear choke defense (against a wall)"

print("\n== clean_fields")
k, f = cr.clean_fields({"segment_key": "C0022_01", "technique": "  52 x  "})
ok(f == {"technique": "  52 x  "}, "technique kept verbatim, not trimmed")
ok(cr.clean_fields({"segment_key": "A1", "technique": ""})[1] == {"technique": None}, "empty technique clears it")
ok(cr.clean_fields({"segment_key": "A1", "note": None})[1] == {"note": ""}, "null note -> empty")
for bad in ({"segment_key": "../x", "note": "a"}, {"segment_key": "A1"}, {"segment_key": "A1", "is_best": "yes"},
            {"segment_key": "A1", "technique": 5}, "not a dict", {"segment_key": "A1", "technique": "x" * 301}):
    try:
        cr.clean_fields(bad); ok(False, "rejects %r" % (bad,))
    except ValueError:
        ok(True, "rejects %s" % (str(bad)[:40],))
ok(len(cr.clean_fields({"segment_key": "A1", "note": "n" * 5000})[1]["note"]) == cr.MAX_NOTE, "note capped")

print("\n== one best take per technique (server-owned)")
rows = {}
cr.apply_answer(rows, CLIP, "A1", {"technique": T52})
cr.apply_answer(rows, CLIP, "B1", {"technique": T52})
ch = cr.apply_answer(rows, CLIP, "A1", {"is_best": True})
ok(rows["A1"]["is_best"] and list(ch) == ["A1"], "first star: only the target changes")
ch = cr.apply_answer(rows, CLIP, "B1", {"is_best": True})
ok(rows["B1"]["is_best"] and not rows["A1"]["is_best"], "star on B1 clears A1 (same technique, other clip)")
ok(set(ch) == {"A1", "B1"} and ch["A1"]["is_best"] is False, "response lists the un-starred row")
cr.apply_answer(rows, CLIP, "A2", {"technique": T95a, "is_best": True})
cr.apply_answer(rows, CLIP, "A3", {"technique": T95b, "is_best": True})
ok(rows["A2"]["is_best"] and rows["A3"]["is_best"], "two 95s are different techniques (verbatim strings)")

print("\n== unnamed segments: scope is the camera clip")
rows = {}
cr.apply_answer(rows, CLIP, "A1", {"is_best": True})
ch = cr.apply_answer(rows, CLIP, "A2", {"is_best": True})
ok(not rows["A1"]["is_best"] and rows["A2"]["is_best"], "unnamed A2 takes the star from unnamed A1 (same clip)")
cr.apply_answer(rows, CLIP, "B1", {"is_best": True})
ok(rows["A2"]["is_best"] and rows["B1"]["is_best"], "other clip is a different scope")
cr.apply_answer(rows, CLIP, "A3", {"technique": T52, "is_best": True})
ok(rows["A2"]["is_best"], "a NAMED star does not clear an unnamed one in the same clip")

print("\n== renaming a starred segment re-applies the rule in its new group")
rows = {}
cr.apply_answer(rows, CLIP, "A1", {"technique": T52, "is_best": True})
cr.apply_answer(rows, CLIP, "B1", {"technique": T95a, "is_best": True})
ch = cr.apply_answer(rows, CLIP, "B1", {"technique": T52})
ok(rows["B1"]["is_best"] and not rows["A1"]["is_best"], "B1 renamed into T52 keeps its star; A1 loses it")
ok("A1" in ch, "and the page is told")
ch = cr.apply_answer(rows, CLIP, "B1", {"is_best": False})
ok(not rows["B1"]["is_best"] and list(ch) == ["B1"], "un-starring touches nothing else")
ch = cr.apply_answer(rows, CLIP, "B1", {"note": "good"})
ok(ch == {"B1": {"technique": T52, "is_best": False, "note": "good"}}, "note-only change returns the row")
same = cr.apply_answer(rows, CLIP, "B1", {"note": "good"})
ok(list(same) == ["B1"], "a no-op still answers with the row (retries are idempotent)")

print("\n== tokens, media, csv")
ok(cr.sha("abc") == hashlib.sha256(b"abc").hexdigest(), "sha256 of the token")
tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, "rv"))
TOK, TOK2 = "Tok_" + "x" * 30, "Other-" + "y" * 30
json.dump({"review_id": "rv1", "title": "T", "slack_channel": "C1",
           "reviewers": [{"label": "Guest", "token_sha256": cr.sha(TOK)},
                         {"label": "QA", "token_sha256": cr.sha(TOK2)}]},
          open(os.path.join(tmp, "rv", "review.json"), "w"))
json.dump([{"key": k, "clip": c, "rep_n": 1, "rep_of": 2, "wall_clock": "13:00:00", "duration_s": 9,
            "weapon": ""} for k, c in CLIP.items()], open(os.path.join(tmp, "rv", "segments.json"), "w"))
open(os.path.join(tmp, "rv", "page.html"), "w").write("<html>page</html>")
R = cr.load_reviews(tmp)
ok(list(R) == ["rv1"] and R["rv1"].clip_of["B2"] == "C2", "review loads from disk")
ok(cr.find_review(R, TOK)[2] == "Guest", "token finds its reviewer")
ok(cr.find_review(R, "short")[0] is None and cr.find_review(R, "Z" * 30)[0] is None, "short / unknown tokens find nothing")
ok(cr.find_review(R, "../../etc/passwd" + "a" * 20)[0] is None, "path-like token rejected")
ok(cr.media_ok("poster", b"\xff\xd8" + b"0" * 900) and not cr.media_ok("poster", b"PNG" + b"0" * 900), "poster must be JPEG")
ok(cr.media_ok("clip", b"\x00\x00\x00\x18ftypisom" + b"0" * 9000) and not cr.media_ok("clip", b"x" * 9000), "clip must be mp4")
ok(not cr.media_ok("clip", b"\x00\x00\x00\x18ftyp" + b"0" * 5_000_000), "oversize clip refused")
csvt = cr.to_csv(R["rv1"], [{"label": "Guest", "segment_key": "A1", "technique": T52, "is_best": True,
                             "note": "a\nb", "updated_at": "t"}])
ok("BEST" in csvt and T52 in csvt and "a b" in csvt and "C1" in csvt, "csv carries technique verbatim, BEST, flattened note")

print("\n== routes (fake storage)")
try:
    from flask import Flask
except ImportError:
    print("  (flask missing — route checks skipped)"); Flask = None

if Flask:
    DB, MEDIA, PINGS = {}, {}, []
    import types
    KV = {}
    sys.modules["pg_store"] = types.SimpleNamespace(load_state=lambda k, d=None: KV.get(k, d),
                                                    save_state=lambda k, v: KV.__setitem__(k, v),
                                                    enabled=lambda: True)

    def f_answer(review, h, key, fields, ts=None, ua=""):
        rows = DB.setdefault((review.review_id, h), {})
        return cr.apply_answer(rows, review.clip_of, key, fields)

    cr.db_answer = f_answer
    cr.db_answers_for = lambda rid, h: {k: dict(v) for k, v in DB.get((rid, h), {}).items()}

    def f_put(rid, key, kind, data):
        if (rid, key, kind) in MEDIA:
            return False
        MEDIA[(rid, key, kind)] = data; return True

    cr.db_media_put_once = f_put
    cr.db_media_get = lambda rid, key, kind: MEDIA.get((rid, key, kind))
    cr.db_media_count = lambda rid: {}

    def f_all(rid):
        ans = []
        for (r, h), rows in DB.items():
            if r == rid:
                for k, v in rows.items():
                    ans.append(dict(v, token_hash=h, segment_key=k, updated_at="2026-09-26T12:00:00"))
        by = {}
        for a in ans:
            by.setdefault(a["token_hash"], {})[a["segment_key"]] = a
        return ans, {}, by

    cr.db_all = f_all
    app = Flask(__name__)
    cr.register(app, admin_ok=lambda s: s == "adm", notify=lambda ch, t: PINGS.append((ch, t)), reviews=R)
    c = app.test_client()

    r = c.get("/r/%s" % TOK)
    ok(r.status_code == 302 and r.headers["Location"].endswith("/r/%s/" % TOK), "no trailing slash -> redirect (media paths are relative)")
    r = c.get("/r/%s/" % TOK)
    ok(r.status_code == 200 and b"page" in r.data, "page served on a good token")
    ok("noindex" in r.headers.get("X-Robots-Tag", "") and r.headers.get("Referrer-Policy") == "no-referrer", "noindex + no-referrer")
    ok(c.get("/r/%s/" % ("Q" * 30)).status_code == 404, "unknown token -> plain 404")
    ok(c.get("/api/%s/answers" % ("Q" * 30)).status_code == 404, "unknown token cannot read answers")

    jpg = b"\xff\xd8" + b"1" * 1000
    mp4 = b"\x00\x00\x00\x18ftypisom" + b"2" * 20000
    r = c.post("/r/%s/setup/poster/A1" % TOK, data=jpg)
    ok(r.status_code == 200, "poster uploads once")
    r = c.post("/r/%s/setup/poster/A1" % TOK, data=b"\xff\xd8" + b"9" * 1000)
    ok(r.status_code == 409 and MEDIA[("rv1", "A1", "poster")] == jpg, "second upload refused: media is write-once")
    ok(c.post("/r/%s/setup/clip/NOPE" % TOK, data=mp4).status_code == 404, "unknown segment key refused")
    ok(c.post("/r/%s/setup/clip/A1" % TOK, data=b"junk" * 3000).status_code == 400, "non-mp4 refused")
    c.post("/r/%s/setup/clip/A1" % TOK, data=mp4)
    r = c.get("/r/%s/c/A1.mp4" % TOK, headers={"Range": "bytes=0-99"})
    ok(r.status_code == 206 and len(r.data) == 100 and r.headers["Content-Range"].endswith("/%d" % len(mp4)), "clip answers Range (iOS)")
    ok(c.get("/r/%s/p/A1.jpg" % TOK).data == jpg, "poster served")
    ok(c.get("/r/%s/p/A1.jpg" % ("Q" * 30)).status_code == 404, "media needs the token")

    post = lambda tok, body: c.post("/api/%s/answer" % tok, data=json.dumps(body), content_type="application/json")
    r = post(TOK, {"segment_key": "A1", "technique": T52, "ts": 1})
    ok(r.status_code == 200 and r.get_json()["changed"]["A1"]["technique"] == T52, "answer saved, row echoed")
    post(TOK, {"segment_key": "B1", "technique": T52})
    post(TOK, {"segment_key": "A1", "is_best": True})
    r = post(TOK, {"segment_key": "B1", "is_best": True})
    ch = r.get_json()["changed"]
    ok(ch["A1"]["is_best"] is False and ch["B1"]["is_best"] is True, "server moves the star and says so")
    post(TOK2, {"segment_key": "A1", "technique": T52, "is_best": True})
    got = c.get("/api/%s/answers" % TOK).get_json()["answers"]
    ok(got["B1"]["is_best"] and not got["A1"]["is_best"], "another reviewer's star does not touch this one")
    ok(post(TOK, {"segment_key": "ZZ", "note": "x"}).status_code == 400, "unknown segment -> 400 (page drops it, no loop)")
    ok(post(TOK, {"segment_key": "A1"}).status_code == 400, "empty change -> 400")
    import time as _t; _t.sleep(0.3)
    ok(sum("first answer" in t for _, t in PINGS) == 2 and all(ch == "C1" for ch, _ in PINGS),
       "Slack ping once per reviewer on the first answer, to the review's channel")
    for k2 in ("A2", "A3", "B2"):
        post(TOK, {"segment_key": k2, "technique": T95a})
    _t.sleep(0.3)
    ok(sum("named all" in t for _, t in PINGS) == 1, "Slack ping when every segment is named")

    ok(c.get("/admin/review/rv1").status_code == 401, "admin page needs a login")
    ok(c.get("/admin/review/rv1?secret=adm").status_code == 200, "admin page with the admin key")
    d = c.get("/admin/review/rv1.json?secret=adm").get_json()
    g = [p for p in d["reviewers"] if p["label"] == "Guest"][0]
    ok(g["named"] == 5 and g["of"] == 5 and g["techniques_without_best"] == 1, "progress: 5 of 5 named, 1 technique still without a best take")
    bt = [t for t in d["by_technique"] if t["label"] == "Guest"][0]
    ok(bt["best"] == "B1" and bt["others"] == ["A1"], "per-technique view: best take next to the also-rans")
    r = c.get("/admin/review/rv1.csv?secret=adm")
    ok(r.status_code == 200 and "attachment" in r.headers["Content-Disposition"] and T52 in r.get_data(as_text=True), "csv export")
    ok(c.get("/admin/review/nope?secret=adm").status_code == 404, "unknown review -> 404")

shutil.rmtree(tmp)
print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
