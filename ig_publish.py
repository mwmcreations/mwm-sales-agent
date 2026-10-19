"""Patch #244 - one-shot Instagram publisher (ERIC's minimal version).

Michael approves one exact post (file + caption + kind) in chat; DEV or ERIC
then calls POST /admin/ig-publish through the Mac daemon (the admin secret
never leaves the Mac). The server streams the Drive file to Meta on a one-time
URL, waits for Meta to finish the container, publishes, and posts the
permalink (or Meta's error) to #dev. Nothing here runs on a timer: no queue,
no schedule, no auto-publish. The Monday approval queue is the full version.

Pure helpers + an injectable runner so the gate can test every branch.
"""
import json
import re
import secrets
import time

GRAPH = "https://graph.instagram.com/v21.0"
MEDIA_PATH = "/ig/media/"
TOKEN_TTL_S = 2 * 3600
POLL_EVERY_S = 10
POLL_MAX_S = 20 * 60
KINDS = ("reel", "story")

BANNED_PHRASES = ("no led wall", "no green screen")
# Product names must be written exactly; these catch the near-misses.
PRODUCT_EXACT = ("AI Wall Session",)
_PRODUCT_RX = re.compile(r"\bai[\s-]*wall[\s-]*(spot|session)s?\b", re.I)
# PATCH #255 (Michael, 19 Oct): "AI Wall Spot" is retired -> "Full Immersion".
_RETIRED_RX = re.compile(r"\bai[\s-]*wall[\s-]*spots?\b", re.I)
_FI_RX = re.compile(r"\bfull[\s-]*immersion\b", re.I)

LIMITS = {   # seconds, bytes - conservative versions of Meta's published limits
    "reel": {"min_s": 3, "max_s": 15 * 60, "max_bytes": 1024 * 1024 * 1024},
    "story": {"min_s": 3, "max_s": 60, "max_bytes": 100 * 1024 * 1024},
}
VIDEO_MIMES = ("video/mp4", "video/quicktime")


def caption_problems(caption, kind):
    out = []
    c = caption or ""
    low = c.lower()
    for p in BANNED_PHRASES:
        if p in low:
            out.append('caption contains "%s" (not allowed)' % p)
    for m in _PRODUCT_RX.finditer(c):
        word = m.group(0)
        if _RETIRED_RX.fullmatch(word):
            out.append('"%s" is a retired name - write "Full Immersion"' % word)
        elif word not in PRODUCT_EXACT:
            out.append('product name written "%s" - must be exactly "AI Wall Session"' % word)
    for m in _FI_RX.finditer(c):
        if m.group(0) not in ("Full Immersion", "FULL IMMERSION"):
            out.append('product name written "%s" - must be exactly "Full Immersion"' % m.group(0))
    if kind == "reel" and not c.strip():
        out.append("a Reel needs a caption")
    if len(c) > 2200:
        out.append("caption is %d characters (Instagram allows 2,200)" % len(c))
    if c.count("#") > 30:
        out.append("more than 30 hashtags")
    return out


def video_problems(meta, kind):
    """meta: Drive file fields {name, mimeType, size, videoMediaMetadata{width,height,durationMillis}}."""
    out = []
    if kind not in KINDS:
        return ["kind must be reel or story"]
    if not isinstance(meta, dict) or not meta:
        return ["could not read the file in Drive"]
    lim = LIMITS[kind]
    if meta.get("mimeType") not in VIDEO_MIMES:
        out.append("file type %s is not MP4/MOV" % meta.get("mimeType"))
    try:
        size = int(meta.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if size and size > lim["max_bytes"]:
        out.append("file is %d MB (limit %d MB for a %s)" % (size // 1048576, lim["max_bytes"] // 1048576, kind))
    vm = meta.get("videoMediaMetadata") or {}
    try:
        dur = int(vm.get("durationMillis") or 0) / 1000.0
    except (TypeError, ValueError):
        dur = 0
    if dur:
        if dur < lim["min_s"]:
            out.append("video is %.1f s (minimum %d s)" % (dur, lim["min_s"]))
        if dur > lim["max_s"]:
            out.append("video is %.0f s (maximum %d s for a %s)" % (dur, lim["max_s"], kind))
    w, h = vm.get("width"), vm.get("height")
    try:
        if w and h and float(h) / float(w) < 1.7:
            out.append("video is %sx%s; Reels and Stories must be vertical 9:16" % (w, h))
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return out


def release_problem(client_in_frame, release_ok):
    if client_in_frame and not release_ok:
        return "a client is in frame and release_ok is not set"
    return None


def new_media_token():
    return secrets.token_urlsafe(24)


def thumb_problem(thumb_offset, meta, kind):
    """Patch #244b: Reel cover frame, milliseconds from the start. None/'' = Instagram's default."""
    if thumb_offset in (None, ""):
        return None
    if kind != "reel":
        return "a cover frame only applies to a Reel"
    try:
        ms = int(str(thumb_offset).strip())
    except (TypeError, ValueError):
        return "thumb_offset must be whole milliseconds"
    if ms < 0:
        return "thumb_offset cannot be negative"
    try:
        dur = int(((meta or {}).get("videoMediaMetadata") or {}).get("durationMillis") or 0)
    except (TypeError, ValueError):
        dur = 0
    if dur and ms >= dur:
        return "thumb_offset %d ms is past the end of the video (%d ms)" % (ms, dur)
    return None


# ── PATCH #246 — collaborators + user tags (ERIC, 14 Oct: Michael wants his
# personal account on MWM posts). Reels/feed only; a Story has neither.
# `collaborators` sends the collab invite (the post shows on the other
# profile once they accept); `user_tags` tags the account on the Reel —
# usernames only, no x/y on a Reel. Format is checked here; whether the
# account exists is Meta's answer at container time (it comes back as the
# failure line in #dev/#eric), because a personal account cannot be looked
# up through business_discovery.
USERNAME_RX = re.compile(r"^[a-z0-9._]{1,30}$")
MAX_COLLABORATORS = 3
MAX_USER_TAGS = 20


def parse_usernames(raw, limit, label):
    """'@michellmoraes, MWM.creations' -> (['michellmoraes', 'mwm.creations'], None)
    or ([], 'problem'). Lower-cased, de-duplicated, leading @ dropped."""
    out, seen = [], set()
    for tok in re.split(r"[,\s]+", str(raw or "")):
        u = tok.strip().lstrip("@").lower()
        if not u:
            continue
        if not USERNAME_RX.match(u) or u.startswith(".") or u.endswith(".") or ".." in u:
            return [], "%s: '%s' is not an Instagram username (letters, numbers, periods, underscores, up to 30)" % (label, tok.strip()[:40])
        if u not in seen:
            seen.add(u)
            out.append(u)
    if len(out) > limit:
        return [], "%s: at most %d, got %d" % (label, limit, len(out))
    return out, None


def people_problems(kind, collaborators, user_tags):
    """-> (collab_list, tag_list, [problems])."""
    problems = []
    c, pc = parse_usernames(collaborators, MAX_COLLABORATORS, "collaborators")
    if pc:
        problems.append(pc)
    t, pt = parse_usernames(user_tags, MAX_USER_TAGS, "user_tags")
    if pt:
        problems.append(pt)
    if kind == "story" and (c or t):
        problems.append("collaborators and user_tags apply to a Reel, not a Story")
    return c, t, problems


def container_params(kind, video_url, caption, thumb_offset=None, collaborators=None, user_tags=None):
    if kind == "story":
        return {"media_type": "STORIES", "video_url": video_url}
    p = {"media_type": "REELS", "video_url": video_url, "caption": caption or "", "share_to_feed": "true"}
    if thumb_offset not in (None, ""):
        p["thumb_offset"] = str(int(str(thumb_offset).strip()))
    if collaborators:
        p["collaborators"] = json.dumps(list(collaborators)[:MAX_COLLABORATORS])
    if user_tags:
        p["user_tags"] = json.dumps([{"username": u} for u in list(user_tags)[:MAX_USER_TAGS]])
    return p


def run_publish(job, http, token, ig_user_id, sleep=time.sleep, now=time.time, log=lambda *_: None):
    """Create container -> wait FINISHED -> publish -> permalink. Mutates job and returns it.
    http: object with get(url, params, timeout) and post(url, data, timeout) returning
    objects with .status_code and .json(). Never puts the token anywhere but params."""
    def _err(stage, r=None, extra=""):
        msg = extra
        try:
            if r is not None:
                e = (r.json() or {}).get("error") or {}
                msg = (e.get("error_user_msg") or e.get("message") or msg or "HTTP %s" % r.status_code)
        except Exception:
            msg = msg or "HTTP %s" % getattr(r, "status_code", "?")
        job.update(status="failed", stage=stage, error=str(msg)[:400])
        return job

    job.update(status="creating")
    r = http.post("%s/%s/media" % (GRAPH, ig_user_id),
                  data=dict(container_params(job["kind"], job["video_url"], job.get("caption"), job.get("thumb_offset"),
                                             job.get("collaborators"), job.get("user_tags")), access_token=token), timeout=60)
    cid = (r.json() or {}).get("id") if r.status_code == 200 else None
    if not cid:
        return _err("create", r)
    job.update(container_id=cid, status="processing")
    t0 = now()
    while True:
        s = http.get("%s/%s" % (GRAPH, cid), params={"fields": "status_code,status", "access_token": token}, timeout=30)
        d = (s.json() or {}) if s.status_code == 200 else {}
        code = d.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            return _err("processing", None, d.get("status") or code)
        if now() - t0 > POLL_MAX_S:
            return _err("processing", None, "Meta did not finish processing in %d min" % (POLL_MAX_S // 60))
        sleep(POLL_EVERY_S)
    job.update(status="publishing")
    p = http.post("%s/%s/media_publish" % (GRAPH, ig_user_id), data={"creation_id": cid, "access_token": token}, timeout=60)
    mid = (p.json() or {}).get("id") if p.status_code == 200 else None
    if not mid:
        return _err("publish", p)
    job.update(media_id=mid, status="published")
    try:
        q = http.get("%s/%s" % (GRAPH, mid), params={"fields": "permalink", "access_token": token}, timeout=30)
        job["permalink"] = (q.json() or {}).get("permalink") if q.status_code == 200 else None
    except Exception:
        job["permalink"] = None
    return job
