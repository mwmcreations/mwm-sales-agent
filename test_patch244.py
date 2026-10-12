"""PATCH #244 gate - one-shot Instagram publisher. Pure checks + the runner with
a fake Graph API, static wiring of the routes. Prints "N passed, M failed",
then runs the #243 gate (which chains on)."""
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


# caption rules
check("cap.clean", igp.caption_problems("Book your AI Wall Session at MWM Studios.", "reel") == [])
check("cap.banned", any("no led wall" in p for p in igp.caption_problems("Real set. No LED wall. No green screen.", "reel")))
check("cap.banned2", len(igp.caption_problems("no green screen here", "reel")) == 1)
check("cap.product_case", len(igp.caption_problems("Try the AI wall session", "reel")) == 1)
check("cap.product_hyphen", len(igp.caption_problems("AI-Wall Spot now open", "reel")) == 1)
check("cap.product_ok_both", igp.caption_problems("AI Wall Spot or AI Wall Session", "reel") == [])
check("cap.reel_needs_caption", igp.caption_problems("  ", "reel") != [] and igp.caption_problems("", "story") == [])
check("cap.length", igp.caption_problems("x" * 2201, "reel") != [])
check("cap.hashtags", igp.caption_problems(" ".join("#t%d" % i for i in range(31)), "reel") != [])

# video spec
ok_meta = {"name": "a.mp4", "mimeType": "video/mp4", "size": "50000000",
           "videoMediaMetadata": {"width": 1080, "height": 1920, "durationMillis": 30000}}
check("vid.ok", igp.video_problems(ok_meta, "reel") == [] and igp.video_problems(ok_meta, "story") == [])
check("vid.kind", igp.video_problems(ok_meta, "post") == ["kind must be reel or story"])
check("vid.missing", igp.video_problems({}, "reel") == ["could not read the file in Drive"])
check("vid.mime", igp.video_problems(dict(ok_meta, mimeType="image/jpeg"), "reel") != [])
check("vid.landscape", igp.video_problems(dict(ok_meta, videoMediaMetadata={"width": 1920, "height": 1080, "durationMillis": 30000}), "reel") != [])
check("vid.story_long", igp.video_problems(dict(ok_meta, videoMediaMetadata={"width": 1080, "height": 1920, "durationMillis": 90000}), "story") != []
      and igp.video_problems(dict(ok_meta, videoMediaMetadata={"width": 1080, "height": 1920, "durationMillis": 90000}), "reel") == [])
check("vid.too_short", igp.video_problems(dict(ok_meta, videoMediaMetadata={"width": 1080, "height": 1920, "durationMillis": 1000}), "reel") != [])
check("vid.story_size", igp.video_problems(dict(ok_meta, size=str(200 * 1048576)), "story") != [])

# release
check("rel", igp.release_problem(True, False) and not igp.release_problem(True, True) and not igp.release_problem(False, False))

# container params
check("params.reel", igp.container_params("reel", "U", "C") == {"media_type": "REELS", "video_url": "U", "caption": "C", "share_to_feed": "true"})
check("params.story", igp.container_params("story", "U", "C") == {"media_type": "STORIES", "video_url": "U"})


# Patch #244b - cover frame
check("thumb.none", igp.thumb_problem(None, ok_meta, "reel") is None and igp.thumb_problem("", ok_meta, "reel") is None)
check("thumb.ok", igp.thumb_problem("7000", ok_meta, "reel") is None)
check("thumb.past_end", igp.thumb_problem("30000", ok_meta, "reel") is not None)
check("thumb.bad", igp.thumb_problem("7s", ok_meta, "reel") is not None and igp.thumb_problem("-1", ok_meta, "reel") is not None)
check("thumb.story", igp.thumb_problem("1000", ok_meta, "story") is not None)
check("thumb.param", igp.container_params("reel", "U", "C", "7000").get("thumb_offset") == "7000"
      and "thumb_offset" not in igp.container_params("reel", "U", "C") and "thumb_offset" not in igp.container_params("story", "U", "C", "7000"))


class R:
    def __init__(s, code, d): s.status_code = code; s._d = d
    def json(s): return s._d


class FakeHTTP:
    def __init__(s, create=(200, {"id": "C1"}), statuses=("IN_PROGRESS", "FINISHED"), publish=(200, {"id": "M1"}),
                 permalink="https://www.instagram.com/reel/x/"):
        s.create, s.statuses, s.publish, s.permalink = create, list(statuses), publish, permalink
        s.calls = []
    def post(s, url, data=None, timeout=None):
        s.calls.append(("POST", url, dict(data)))
        return R(*s.create) if url.endswith("/media") else R(*s.publish)
    def get(s, url, params=None, timeout=None):
        s.calls.append(("GET", url, dict(params)))
        if params.get("fields") == "permalink":
            return R(200, {"permalink": s.permalink})
        st = s.statuses.pop(0) if s.statuses else "IN_PROGRESS"
        return R(200, {"status_code": st, "status": "Error: bad codec" if st == "ERROR" else st})


clock = {"t": 0}
def fnow(): return clock["t"]
def fsleep(n): clock["t"] += n

job = {"kind": "reel", "video_url": "https://h/ig/media/T", "caption": "hi", "thumb_offset": "7000"}
h = FakeHTTP()
igp.run_publish(job, h, "TOK", "IGU", sleep=fsleep, now=fnow)
check("run.happy", job["status"] == "published" and job["media_id"] == "M1" and job["permalink"].startswith("https://www.instagram.com/"))
check("run.create_params", h.calls[0][2]["media_type"] == "REELS" and h.calls[0][2]["video_url"] == "https://h/ig/media/T"
      and h.calls[0][1].endswith("/IGU/media"))
check("run.thumb_sent", h.calls[0][2].get("thumb_offset") == "7000")
check("run.publish_creation", any(c[1].endswith("/IGU/media_publish") and c[2]["creation_id"] == "C1" for c in h.calls))

job = {"kind": "reel", "video_url": "U", "caption": "hi"}
igp.run_publish(job, FakeHTTP(create=(400, {"error": {"message": "Unsupported video", "error_user_msg": "The video format is not supported"}})),
                "TOK", "IGU", sleep=fsleep, now=fnow)
check("run.create_fail", job["status"] == "failed" and job["stage"] == "create" and "not supported" in job["error"] and "media_id" not in job)

job = {"kind": "reel", "video_url": "U", "caption": "hi"}
h = FakeHTTP(statuses=("IN_PROGRESS", "ERROR"))
igp.run_publish(job, h, "TOK", "IGU", sleep=fsleep, now=fnow)
check("run.processing_error", job["status"] == "failed" and job["stage"] == "processing" and not any("media_publish" in c[1] for c in h.calls))

clock["t"] = 0
job = {"kind": "reel", "video_url": "U", "caption": "hi"}
h = FakeHTTP(statuses=())
igp.run_publish(job, h, "TOK", "IGU", sleep=fsleep, now=fnow)
check("run.timeout", job["status"] == "failed" and "did not finish" in job["error"] and not any("media_publish" in c[1] for c in h.calls))

job = {"kind": "story", "video_url": "U"}
igp.run_publish(job, FakeHTTP(publish=(400, {"error": {"message": "limit reached"}})), "TOK", "IGU", sleep=fsleep, now=fnow)
check("run.publish_fail", job["status"] == "failed" and job["stage"] == "publish" and "limit" in job["error"])
check("run.no_token_in_job", "TOK" not in repr(job))
check("token.unique", igp.new_media_token() != igp.new_media_token() and len(igp.new_media_token()) >= 24)

# static wiring
SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("wire.import", "import ig_publish as _igp" in SRC)
rt = SRC[SRC.index("def admin_ig_publish():"):SRC.index("def admin_ig_publish_status():")]
i_auth = rt.index("_admin_secret_ok(")
i_appr = rt.index('if approved_by != "michael":')
i_chk = rt.index("_igp.caption_problems(")
i_dry = rt.index("if dry_run:")
i_thr = rt.index("threading.Thread(target=_igp_worker")
check("wire.order", i_auth < i_appr < i_chk < i_dry < i_thr)
check("wire.one_at_a_time", "another post is still publishing" in rt and "_IGP_LOCK" in rt)
wk = SRC[SRC.index("def _igp_worker("):SRC.index("@app.route('/admin/ig-publish', methods=['POST'])")]
check("wire.token_dies", "_IGP_TOKENS.pop(tok, None)" in wk and "finally:" in wk)
check("wire.no_token_in_slack", "INSTAGRAM_ACCESS_TOKEN" not in wk.split("finally:")[1] and "video_url" not in wk)
md = SRC[SRC.index("def ig_publish_media(tok):"):SRC.index("def _igp_worker(")]
check("wire.media_expiry", 'time.time() > ent["exp"]' in md and "404" in md)
check("wire.status_hides_url", '"video_url"' in SRC[SRC.index("def _igp_public("):SRC.index("@app.route(_igp.MEDIA_PATH")])
check("wire.thumb", "_igp.thumb_problem(thumb_offset, meta, kind)" in rt and '"thumb_offset": thumb_offset or None' in rt)
check("wire.status_auth", "_admin_secret_ok(" in SRC[SRC.index("def admin_ig_publish_status():"):SRC.index("def admin_ig_publish_status():") + 300])

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch243.py")], capture_output=True, text=True)
tail = (r_.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #243 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("chain: " + tail)
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
