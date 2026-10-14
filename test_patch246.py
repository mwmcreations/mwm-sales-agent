"""PATCH #246 gate — /admin/ig-publish takes `collaborators` (<=3 usernames,
collab invite on Reels) and `user_tags` (usernames, no x/y on a Reel);
format-checked, refused on a Story, echoed in the dry run, sent to Meta on
the container, named in the #dev/#eric line. Then runs the #245 gate
(→ 244 → 243 → 160 → …) and the #161 gate (→ 160 → …)."""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ig_publish as igp   # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


check("parse.basic", igp.parse_usernames("@michellmoraes, MWM.creations", 3, "c") == (["michellmoraes", "mwm.creations"], None))
check("parse.dedupe_ws", igp.parse_usernames(" a_1  @a_1\nb.c ", 3, "c") == (["a_1", "b.c"], None))
check("parse.empty", igp.parse_usernames("", 3, "c") == ([], None) and igp.parse_usernames(None, 3, "c") == ([], None))
check("parse.limit", igp.parse_usernames("a,b,c,d", 3, "collaborators")[1] == "collaborators: at most 3, got 4")
for bad in ("name!", "a" * 31, ".lead", "trail.", "dou..ble", "ação", "semi;colon"):
    r = igp.parse_usernames(bad, 5, "user_tags")
    check(f"parse.bad {bad!r}", r[0] == [] and r[1] and r[1].startswith("user_tags:"), r)
check("people.reel_ok", igp.people_problems("reel", "michellmoraes", "michellmoraes, mwm.creations") == (["michellmoraes"], ["michellmoraes", "mwm.creations"], []))
check("people.story_refused", "apply to a Reel, not a Story" in igp.people_problems("story", "x", "")[2][0]
      and igp.people_problems("story", "", "")[2] == [])
check("people.both_problems", len(igp.people_problems("reel", "a,b,c,d", "bad!")[2]) == 2)
check("limits", igp.MAX_COLLABORATORS == 3 and igp.MAX_USER_TAGS == 20)
p = igp.container_params("reel", "U", "C", "7000", ["michellmoraes"], ["michellmoraes", "mwm.creations"])
check("params.json", p["collaborators"] == '["michellmoraes"]' and p["user_tags"] == '[{"username": "michellmoraes"}, {"username": "mwm.creations"}]'
      and p["thumb_offset"] == "7000" and p["share_to_feed"] == "true")
check("params.absent_when_empty", "collaborators" not in igp.container_params("reel", "U", "C") and "user_tags" not in igp.container_params("reel", "U", "C", None, [], []))
check("params.story_never", "collaborators" not in igp.container_params("story", "U", "C", None, ["x"], ["y"]))
check("params.caps", igp.container_params("reel", "U", "C", None, ["a", "b", "c", "d"], None)["collaborators"] == '["a", "b", "c"]')


class R:
    def __init__(s, code, d): s.status_code = code; s._d = d
    def json(s): return s._d


class FakeHTTP:
    def __init__(s):
        s.calls = []
    def post(s, url, data=None, timeout=None):
        s.calls.append(("POST", url, dict(data)))
        return R(200, {"id": "C1"}) if url.endswith("/media") else R(200, {"id": "M1"})
    def get(s, url, params=None, timeout=None):
        if params.get("fields") == "permalink":
            return R(200, {"permalink": "https://www.instagram.com/reel/x/"})
        return R(200, {"status_code": "FINISHED"})


job = {"kind": "reel", "video_url": "U", "caption": "hi", "collaborators": ["michellmoraes"], "user_tags": ["michellmoraes"]}
h = FakeHTTP()
igp.run_publish(job, h, "TOK", "IGU", sleep=lambda n: None, now=lambda: 0)
check("run.sends_people", job["status"] == "published" and h.calls[0][2]["collaborators"] == '["michellmoraes"]'
      and h.calls[0][2]["user_tags"] == '[{"username": "michellmoraes"}]')
job = {"kind": "reel", "video_url": "U", "caption": "hi"}
h = FakeHTTP()
igp.run_publish(job, h, "TOK", "IGU", sleep=lambda n: None, now=lambda: 0)
check("run.unchanged_without", "collaborators" not in h.calls[0][2] and "user_tags" not in h.calls[0][2])

SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
rt = SRC[SRC.index("def admin_ig_publish():"):SRC.index("def admin_ig_publish_status():")]
check("wire.params_read", 'request.values.get("collaborators")' in rt and 'request.values.get("user_tags")' in rt)
check("wire.checked_before_dry_run", "_igp.people_problems(kind, collaborators_raw, user_tags_raw)" in rt
      and rt.index("_igp.people_problems(") < rt.index("if problems:") < rt.index("if dry_run:"))
check("wire.dry_run_echoes", '"collaborators": collaborators, "user_tags": user_tags}' in rt)
check("wire.job_carries", '"collaborators": collaborators, "user_tags": user_tags,' in rt)
wk = SRC[SRC.index("def _igp_worker("):SRC.index("@app.route('/admin/ig-publish', methods=['POST'])")]
check("wire.slack_names_people", 'Collab invite sent to @' in wk and 'Tagged @' in wk and "once accepted" in wk)

print(f"static+behaviour: {passed} passed, {failed} failed")
for gate in ("test_patch245.py", "test_patch161.py"):
    r_ = subprocess.run([sys.executable, os.path.join(HERE, gate)], capture_output=True, text=True)
    tail = (r_.stdout.strip().splitlines() or [""])[-1]
    m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
    if not m:
        print(r_.stdout[-1500:]); print(r_.stderr[-800:])
        failed += 1; print(f"FAIL {gate} did not report")
    else:
        passed += int(m.group(1)); failed += int(m.group(2))
        print(f"{gate}: {tail}")
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
