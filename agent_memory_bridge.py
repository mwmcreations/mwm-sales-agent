#!/usr/bin/env python3
"""
agent_memory_bridge.py — PATCH #263. The Mac answers the app's memory requests.

The agents' memory files live on Michael's Mac (~/Documents/Claude/Memory/<AGENT>.md)
and nowhere else. When the app runs a round for an agent it files a request
{id, agent, file, keywords, head, tail, match_lines}; this bridge, started by
the deploy daemon (mwm_autodeploy.sh) when .deploy/agent_bridge.enabled exists,
polls the app every few seconds, greps the agent's OWN file on this machine
and posts back the matching lines WITH their real line numbers (plus the head
and the tail of the file). Nothing else leaves the Mac: not the file, not
other agents' files, never a secret.

Same shape as vi_render_worker.py: leaves the daemon's process group, one
instance at a time under a lock, listens for LINGER seconds, then exits so
the next daemon pass starts a fresh one. The admin secret arrives in the
environment (AT_SECRET, read by the daemon from ~/.mwm_upload_secret) and is
never logged or written.
"""
import os
try:
    os.setsid()
except OSError:
    pass
import json
import re
import sys
import time
import urllib.parse
import urllib.request

APP = os.environ.get("AT_APP", "https://mwm-sales-agent-production.up.railway.app")
SECRET = os.environ.get("AT_SECRET", "")
MEMORY_DIR = os.path.expanduser(os.environ.get("AT_MEMORY_DIR", "~/Documents/Claude/Memory"))
WORK_DIR = os.path.expanduser(os.environ.get("AT_WORK_DIR", "~/mwm-sales-agent/.deploy/_tools"))
LOG = os.environ.get("AT_LOG", os.path.join(WORK_DIR, "agent_bridge.log"))
LINGER = int(os.environ.get("AT_LINGER", "3300"))        # 55 min, then hand over
POLL = float(os.environ.get("AT_POLL", "6"))            # seconds between polls
LINE_MAX = 400
ALLOWED_FILE = re.compile(r"^[A-Z]{2,8}\.md$")


def log(msg):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


def _get(path, params):
    params = dict(params or {})
    params["secret"] = SECRET
    url = APP + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(path, body):
    body = dict(body or {})
    body["secret"] = SECRET
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(APP + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def excerpt_for(req):
    """{ok, lines: 'N: text\\n...', counts} for one request, from the agent's own file."""
    fname = str(req.get("file") or "")
    if not ALLOWED_FILE.match(fname):
        return {"ok": False, "error": "file name refused"}
    path = os.path.join(MEMORY_DIR, fname)
    if not os.path.isfile(path):
        return {"ok": False, "error": "no such memory file: %s" % fname}
    kws = [str(k).lower() for k in (req.get("keywords") or []) if str(k).strip()]
    head_n = int(req.get("head") or 30)
    tail_n = int(req.get("tail") or 20)
    match_n = int(req.get("match_lines") or 30)
    picked = {}
    matches = []
    total = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, raw in enumerate(f, 1):
            total = i
            line = raw.rstrip("\n")
            if i <= head_n:
                picked[i] = line
            low = line.lower()
            if kws and any(k in low for k in kws):
                matches.append((i, line))
    for i, line in matches[-match_n:]:
        picked[i] = line
    # the tail: re-read the last lines cheaply by index
    if total:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, raw in enumerate(f, 1):
                if i > total - tail_n:
                    picked[i] = raw.rstrip("\n")
    out_lines = []
    for i in sorted(picked):
        t = picked[i]
        if len(t) > LINE_MAX:
            t = t[:LINE_MAX - 1] + "…"
        out_lines.append("%d: %s" % (i, t))
    return {"ok": True, "lines": "\n".join(out_lines), "file_lines": total,
            "matched": len(matches), "served": len(out_lines), "keywords": kws}


def main():
    if not SECRET:
        log("no AT_SECRET in the environment — nothing to do")
        return 2
    os.makedirs(WORK_DIR, exist_ok=True)
    lock = os.path.join(WORK_DIR, "agent_bridge.lock")
    waited = 0.0
    while os.path.exists(lock):
        try:
            pid = int(open(lock).read().strip() or 0)
            os.kill(pid, 0)
            age = time.time() - os.path.getmtime(lock)
            if age >= 3 * 3600:
                log("lock from pid %d is %.0fs old — taking over" % (pid, age))
                break
            if waited >= 30:
                return 0          # another bridge is listening; nothing to do
            time.sleep(5)
            waited += 5
        except (ValueError, ProcessLookupError, PermissionError):
            break
    with open(lock, "w") as f:
        f.write(str(os.getpid()))
    started = time.time()
    served = 0
    log("bridge up (pid %d), memory dir %s" % (os.getpid(), MEMORY_DIR))
    try:
        while time.time() - started < LINGER:
            try:
                pend = _get("/admin/agent-talk/memory-requests", {"bridge": "mac-mini"}).get("requests") or []
            except Exception as e:
                log("could not reach the app: %r" % (e,))
                time.sleep(max(POLL, 15))
                continue
            for req in pend:
                t = time.time()
                res = excerpt_for(req)
                try:
                    ack = _post("/admin/agent-talk/memory", {"id": req.get("id"), "agent": req.get("agent"),
                                                              "result": res, "bridge": "mac-mini"})
                except Exception as e:
                    log("could not post excerpt for %s: %r" % (req.get("id"), e))
                    continue
                served += 1
                log("served %s %s: %s lines (%d matched of %s) in %.1fs -> %s" % (
                    req.get("agent"), req.get("id"), res.get("served", 0), res.get("matched", 0),
                    res.get("file_lines", "?"), time.time() - t, "ok" if ack.get("ok") else ack))
            try:
                with open(lock, "w") as f:
                    f.write(str(os.getpid()))
            except OSError:
                pass
            time.sleep(POLL)
        log("linger over after %d served — handing over" % served)
        return 0
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
