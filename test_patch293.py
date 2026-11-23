#!/usr/bin/env python3
"""GATE for PATCH #293 — share_to_feed on the IG publisher. Prints GATE293 PASS/FAIL."""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ig_publish as igp  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL {name} {str(detail)[:300]}")


check("flag.default", igp.share_flag(None, "reel") == "1" and igp.share_flag("", "reel") == "1" and igp.share_flag("1", "reel") == "1")
check("flag.zero", igp.share_flag("0", "reel") == "0" and igp.share_flag(" 0 ", "reel") == "0" and igp.share_flag("false", "reel") == "0")
check("flag.unknown_is_default", igp.share_flag("maybe", "reel") == "1")
check("flag.story_ignores", igp.share_flag("0", "story") == "1")
p1 = igp.container_params("reel", "https://x/v", "cap")
check("params.default_true", p1["share_to_feed"] == "true" and p1["media_type"] == "REELS", p1)
p0 = igp.container_params("reel", "https://x/v", "cap", share_to_feed=False)
check("params.false", p0["share_to_feed"] == "false", p0)
check("params.others_unchanged", igp.container_params("reel", "u", "c", "1500", ["a"], ["b"], share_to_feed=False)
      == dict(igp.container_params("reel", "u", "c", "1500", ["a"], ["b"]), share_to_feed="false"))
ps = igp.container_params("story", "https://x/v", "", share_to_feed=False)
check("params.story_has_none", "share_to_feed" not in ps and ps["media_type"] == "STORIES", ps)


class R:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


class H:
    def __init__(self):
        self.posts = []

    def post(self, url, data=None, timeout=None):
        self.posts.append((url, dict(data or {})))
        return R(200, {"id": "c1" if url.endswith("/media") else "m1"})

    def get(self, url, params=None, timeout=None):
        return R(200, {"status_code": "FINISHED", "permalink": "https://instagram.com/reel/x"})


for flag, want in (("0", "false"), ("1", "true"), (None, "true")):
    h = H()
    job = {"kind": "reel", "video_url": "https://x/v", "caption": "c"}
    if flag is not None:
        job["share_to_feed"] = flag
    igp.run_publish(job, h, "tok", "123", sleep=lambda *_: None)
    check(f"run.sends_{flag}", h.posts and h.posts[0][1].get("share_to_feed") == want, h.posts[:1])
h = H()
igp.run_publish({"kind": "story", "video_url": "https://x/v", "share_to_feed": "0"}, h, "tok", "123", sleep=lambda *_: None)
check("run.story_no_param", "share_to_feed" not in h.posts[0][1], h.posts[:1])

APP = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("app.parse", 'share_to_feed = _igp.share_flag(request.values.get("share_to_feed"), kind)' in APP)
check("app.checks_echo", 'checks["share_to_feed"] = share_to_feed' in APP)
check("app.job_record", '"share_to_feed": share_to_feed,\n' in APP)
check("app.slack_line", "Reels tab only (not on the profile grid, not in the home feed)." in APP)
for f in ("app.py", "ig_publish.py"):
    check(f"compiles.{f}", subprocess.run([sys.executable, "-m", "py_compile", os.path.join(HERE, f)], capture_output=True).returncode == 0)

print(f"static+behaviour: {passed} passed, {failed} failed")
_prev = max(n for n in range(270, 293) if os.path.exists(os.path.join(HERE, f"test_patch{n}.py")))
r_ = subprocess.run([sys.executable, os.path.join(HERE, f"test_patch{_prev}.py")], capture_output=True, text=True)
tail = [l for l in r_.stdout.strip().splitlines() if l.startswith("TOTAL ")]
mm = re.search(r"TOTAL (\d+) passed, (\d+) failed", tail[-1] if tail else "")
if not mm:
    print(r_.stdout[-1200:]); print(r_.stderr[-600:])
    failed += 1; print(f"FAIL #{_prev} gate did not report")
else:
    passed += int(mm.group(1)); failed += int(mm.group(2))
    print(f"{_prev}: " + tail[-1])
    if int(mm.group(2)):
        print(r_.stdout[-2500:])
print(f"TOTAL {passed} passed, {failed} failed")
print("GATE293 " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
