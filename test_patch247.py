"""PATCH #247 gate — ad videos into the Meta ad account library:
checks, the advideos request, the ready/failed/timeout loop, the route and
worker wiring (token dies, no token in Slack, no campaign writes).
Then runs the #246 gate (→ 245 → … and 161 → …)."""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ad_video as av   # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {detail}")


META = {"id": "F1", "name": "MWM_AD17_MULTINICHE_ADS_APPLY-VISIT_9x16_v01.mp4", "mimeType": "video/mp4", "size": "28884128",
        "md5Checksum": "ed8e0054dd967eca81cc38530d2c61a8", "videoMediaMetadata": {"width": 1080, "height": 1920, "durationMillis": "31570"}}
check("problems.none", av.problems(META) == [])
check("problems.missing", av.problems({}) == ["Drive file not found or not readable by the machine"] and av.problems(None)[0].startswith("Drive file"))
check("problems.mime_size_md5", len(av.problems({"id": "x", "mimeType": "image/png", "size": "0"})) == 3)
check("problems.too_big", any("4 GB" in p for p in av.problems(dict(META, size=str(5 * 1024 ** 3)))))
check("problems.mov_ok", av.problems(dict(META, mimeType="video/quicktime")) == [])
check("title.default", av.title_for(META) == META["name"] and av.title_for(META, "  AD_20  9x16 ") == "AD_20 9x16" and len(av.title_for(META, "x" * 400)) == 255)
check("params", av.upload_params("U", "T") == {"file_url": "U", "title": "T", "name": "T"})
check("account", av.AD_ACCOUNT_DEFAULT == "act_691911781413399" and av.GRAPH.endswith("/v21.0"))


class R:
    def __init__(s, code, d): s.status_code = code; s._d = d
    def json(s): return s._d


class FakeHTTP:
    def __init__(s, post=(200, {"id": "V1"}), statuses=("processing", "ready")):
        s.post_r, s.statuses, s.calls = post, list(statuses), []
    def post(s, url, data=None, timeout=None):
        s.calls.append(("POST", url, dict(data)))
        return R(*s.post_r)
    def get(s, url, params=None, timeout=None):
        s.calls.append(("GET", url, dict(params)))
        st = s.statuses.pop(0) if s.statuses else "processing"
        return R(200, {"id": "V1", "title": "T", "length": 31.57, "status": {"video_status": st, "processing_phase": {"status": "complete"}}})


clock = {"t": 0}
job = {"video_url": "https://h/ig/media/T", "title": "T"}
h = FakeHTTP()
av.run_upload(job, h, "TOK", "act_1", sleep=lambda n: clock.__setitem__("t", clock["t"] + n), now=lambda: clock["t"])
check("run.ready", job["status"] == "ready" and job["video_id"] == "V1" and job["length_s"] == 31.57 and job["title_in_library"] == "T")
check("run.post", h.calls[0][1].endswith("/act_1/advideos") and h.calls[0][2]["file_url"] == "https://h/ig/media/T" and h.calls[0][2]["title"] == "T"
      and h.calls[0][2]["access_token"] == "TOK")
check("run.poll_fields", h.calls[1][1].endswith("/V1") and "status" in h.calls[1][2]["fields"])
check("run.no_token_in_job", "TOK" not in repr(job))
job = {"video_url": "U", "title": "T"}
av.run_upload(job, FakeHTTP(post=(400, {"error": {"message": "Invalid file_url", "error_user_msg": "We couldn't fetch the video"}})), "TOK",
              sleep=lambda n: None, now=lambda: 0)
check("run.upload_fail", job["status"] == "failed" and job["stage"] == "upload" and "fetch" in job["error"] and "video_id" not in job)
job = {"video_url": "U", "title": "T"}
av.run_upload(job, FakeHTTP(statuses=("processing", "error")), "TOK", sleep=lambda n: None, now=lambda: 0)
check("run.processing_error", job["status"] == "failed" and job["stage"] == "processing" and "could not process" in job["error"])
clock["t"] = 0
job = {"video_url": "U", "title": "T"}
av.run_upload(job, FakeHTTP(statuses=()), "TOK", sleep=lambda n: clock.__setitem__("t", clock["t"] + n), now=lambda: clock["t"])
check("run.timeout", job["status"] == "failed" and "did not finish" in job["error"])

SRC = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("wire.import", "import ad_video as _adv" in SRC)
rt = SRC[SRC.index("def admin_ad_video():"):SRC.index("def admin_ad_video_status():")]
check("wire.route", "@app.route('/admin/ad-video', methods=['POST'])" in SRC and '_admin_secret_ok(request.values.get("secret", ""))' in rt
      and rt.index("_admin_secret_ok(") < rt.index("_adv.problems(meta)") < rt.index("if dry_run:") < rt.index("threading.Thread(target=_adv_worker"))
check("wire.md5_read", 'md5Checksum' in SRC[SRC.index("def _adv_drive_meta("):SRC.index("def _adv_worker(")] and '"md5": meta.get("md5Checksum")' in rt)
check("wire.token_env", 'os.getenv("META_ADS_TOKEN", "")' in rt and "META_ADS_TOKEN is not set" in rt)
check("wire.one_at_a_time", "another ad video is still uploading" in rt and "_IGP_LOCK" in rt and "_IGP_TOKENS[tok] = " in rt)
wk = SRC[SRC.index("def _adv_worker("):SRC.index("@app.route('/admin/ad-video', methods=['POST'])")]
check("wire.worker_token_dies", "_IGP_TOKENS.pop(tok, None)" in wk and "finally:" in wk and "META_ADS_TOKEN" not in wk.split("finally:")[1])
check("wire.worker_posts_both", "SLACK_DEV_CHANNEL" in wk and "SLACK_ERIC_CHANNEL" in wk and "md5" in wk and "No campaign, ad set or ad was touched" in wk)
check("wire.no_campaign_writes", "/campaigns" not in rt + wk and "/adsets" not in rt + wk and "/ads\"" not in rt + wk and "budget" not in (rt + wk).lower())
check("wire.account_env", 'META_AD_ACCOUNT_ID = (os.getenv("META_AD_ACCOUNT_ID", "") or _adv.AD_ACCOUNT_DEFAULT).strip()' in SRC)
check("wire.status_route", "@app.route('/admin/ad-video-status', methods=['GET'])" in SRC)

print(f"static+behaviour: {passed} passed, {failed} failed")
r_ = subprocess.run([sys.executable, os.path.join(HERE, "test_patch246.py")], capture_output=True, text=True)
tail = (r_.stdout.strip().splitlines() or [""])[-1]
m = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail)
if not m:
    print(r_.stdout[-1500:]); print(r_.stderr[-800:])
    failed += 1; print("FAIL #246 gate did not report")
else:
    passed += int(m.group(1)); failed += int(m.group(2))
    print("246: " + tail)
print(f"TOTAL {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
